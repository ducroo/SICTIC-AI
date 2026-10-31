import pytest

from lib.datasets.manifest import IngestionManifest
from lib.datasets.paths import dataset_location_for_domain
from lib.insights import InsightFile
from lib.storage import get_storage
from skills.application_feedback import application_feedback as module
from skills.application_feedback.application_feedback import (
    application_feedback,
    open_applications,
)
from skills.submission_ready.submission_ready import proposed_action

MODEL = "ollama/test_model:1b"


def _application(name, step, application_id):
    return {
        "id": application_id,
        "name": name,
        "code": f"CODE-{application_id}",
        "step": step,
    }


class FakeAdapter:
    dealroom_id = "test-room"

    def is_configured(self):
        return True


def _response_report(action, concerns):
    concern_lines = "\n".join(
        f"{index}. {concern}" for index, concern in enumerate(concerns, start=1)
    ) or "- None identified."
    return (
        "# Proposed action\n\n"
        "- Current stage: Application\n"
        f"- Proposed action: {action}\n"
        "- Rationale: Fixture rationale.\n\n"
        "## Eligibility concerns\n\n- None identified.\n\n"
        "## Missing or inconsistent information\n\n"
        f"{concern_lines}\n"
    )


def _indexed_startup(slug):
    storage = get_storage()
    location = dataset_location_for_domain(slug, "startups")
    storage.mkdir(location.raw_rel)
    manifest = IngestionManifest(storage, location.parsed_rel)
    manifest.indexed_dataset_revision = "revision-1"
    manifest.save()


@pytest.fixture
def feedback_run(mock_env, monkeypatch):
    """Fake Dealum and the submission review; collect review and model calls."""
    monkeypatch.setenv("RANKED_LLMS", MODEL)
    monkeypatch.setattr(module, "llm_model", lambda: MODEL)
    monkeypatch.setattr(module, "DealumAdapter", FakeAdapter)
    applications = [
        _application("Beta Labs", "Application", 2),
        _application("Alpha Bio", "Application", 1),
        _application("Gamma Robotics", "Under Review", 3),
        _application("Delta Unknown", "Some new stage", 4),
    ]
    monkeypatch.setattr(module, "list_applications", lambda _adapter: applications)
    reviews = {
        "CODE-1": ("Send concerns to startup", ["Upload the cap table."]),
        "CODE-2": ("Move to Under review", []),
    }
    calls = {"reviews": [], "prompts": []}

    async def fake_submission_ready(selector):
        calls["reviews"].append(selector)
        if selector not in reviews:
            raise RuntimeError(f"review failed for {selector}")
        slug = {"CODE-1": "alpha-bio", "CODE-2": "beta-labs"}[selector]
        _indexed_startup(slug)
        action, concerns = reviews[selector]
        insights = []
        for identifier, content in (
            ("checklist", "# Checklist\n\n| 1 | Cap table | Unclear |\n"),
            ("response", _response_report(action, concerns)),
        ):
            insight = InsightFile(
                dataset=slug,
                skill="submission_ready",
                model=MODEL,
                identifier=identifier,
                subdir=True,
                run_id="20261031T000000Z",
            )
            insight.save(content)
            insights.append(insight)
        return insights

    async def fake_generate_markdown(prompt):
        calls["prompts"].append(prompt)
        return "Dear Alpha Bio team,\n\n1. Please upload your cap table.\n"

    monkeypatch.setattr(module, "submission_ready", fake_submission_ready)
    monkeypatch.setattr(module, "generate_markdown", fake_generate_markdown)
    return reviews, calls


def test_open_applications_selects_only_the_application_stage():
    applications = [
        _application("Beta", "Application", 2),
        _application("alpha", "application", 1),
        _application("Gamma", "Under Review", 3),
        _application("Delta", None, 4),
    ]

    selected = open_applications(applications)

    assert [application["name"] for application in selected] == ["alpha", "Beta"]


def test_open_applications_filters_by_name_or_code_and_rejects_unknown():
    applications = [
        _application("Alpha Bio", "Application", 1),
        _application("Beta Labs", "Application", 2),
        _application("Gamma", "Under Review", 3),
    ]

    assert [a["name"] for a in open_applications(applications, ["alpha bio"])] == ["Alpha Bio"]
    assert [a["name"] for a in open_applications(applications, ["CODE-2"])] == ["Beta Labs"]
    with pytest.raises(ValueError, match="Gamma"):
        open_applications(applications, ["Gamma"])


def test_proposed_action_reads_the_rendered_response():
    assert proposed_action(_response_report("Send concerns to startup", ["x"])) == (
        "Send concerns to startup"
    )
    assert proposed_action("# Manually written review\n") is None


@pytest.mark.asyncio
async def test_feedback_drafts_only_for_applications_with_concerns(feedback_run):
    _reviews, calls = feedback_run

    [summary, draft] = await application_feedback()

    # Only Application-stage applications are reviewed, selected by their code.
    assert calls["reviews"] == ["CODE-1", "CODE-2"]
    assert draft.path == (
        "storage/startups/alpha-bio/insights/"
        "application-feedback-alpha-bio-test-model-1b.md"
    )
    assert "Please upload your cap table." in draft.content()
    prompt = calls["prompts"][0]
    assert "Upload the cap table." in prompt
    assert "Dear Alpha Bio team," in prompt
    assert summary.path.startswith(
        "storage/generated/application-feedback-runs/insights/"
    )
    text = summary.content()
    assert (
        "New or changed drafts: 1. Unchanged drafts: 0. Without concerns: 1. "
        "Failed: 0." in text
    )
    assert "## New or changed drafts\n\n### Alpha Bio (CODE-1)" in text
    assert "https://app.dealum.com/" in text
    assert "Please upload your cap table." in text
    assert "- Beta Labs (CODE-2): Move to Under review." in text
    assert not get_storage().exists(
        "storage/startups/beta-labs/insights/application-feedback-beta-labs-test-model-1b.md"
    )


@pytest.mark.asyncio
async def test_unchanged_review_reuses_the_stored_draft(feedback_run):
    _reviews, calls = feedback_run

    await application_feedback()
    [summary, draft] = await application_feedback()

    assert len(calls["prompts"]) == 1
    text = summary.content()
    assert "New or changed drafts: 0. Unchanged drafts: 1." in text
    assert "## New or changed drafts" not in text
    assert "## Unchanged drafts" in text
    assert "- Alpha Bio (CODE-1): https://app.dealum.com/" in text
    assert f"Draft file: {draft.path}" in text
    assert "Please upload your cap table." not in text


@pytest.mark.asyncio
async def test_failed_review_is_reported_after_the_summary_is_saved(feedback_run):
    reviews, _calls = feedback_run
    del reviews["CODE-2"]

    with pytest.raises(RuntimeError, match="failed for 1 application") as error:
        await application_feedback()

    summary_path = str(error.value).split("see ", 1)[1].split(":", 1)[0]
    text = get_storage().read_text(summary_path)
    assert (
        "New or changed drafts: 1. Unchanged drafts: 0. Without concerns: 0. "
        "Failed: 1." in text
    )
    assert "- Beta Labs (CODE-2): review failed for CODE-2" in text
    assert "### Alpha Bio (CODE-1)" in text


@pytest.mark.asyncio
async def test_feedback_requires_dealum_credentials(mock_env, monkeypatch):
    class UnconfiguredAdapter(FakeAdapter):
        def is_configured(self):
            return False

    monkeypatch.setattr(module, "DealumAdapter", UnconfiguredAdapter)

    with pytest.raises(ValueError, match="DEALUM_API_KEY"):
        await application_feedback()
