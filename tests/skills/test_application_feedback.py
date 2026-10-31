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
from skills.submission_ready.submission_ready import proposed_action, stated_concerns

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
    calls = {"reviews": [], "prompts": [], "reviewers": []}

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

    async def fake_generate_markdown(prompt, reviewer=None):
        calls["prompts"].append(prompt)
        calls["reviewers"].append(reviewer)
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


def test_stated_concerns_reads_both_sections_of_the_response():
    report = _response_report("Send concerns to startup", ["Upload the cap table.", "Name the CEO."])

    assert stated_concerns(report) == ([], ["Upload the cap table.", "Name the CEO."])
    assert stated_concerns("# Manually written review\n") == ([], [])


def test_draft_reviewer_rejects_extra_points_and_a_missing_signature():
    review = module._draft_reviewer(2)
    good = "Dear team,\n\n1. Upload the cap table.\n2. Name the CEO.\n\nBest regards,\n[Screener name]\nSICTIC"

    assert review(good).problems == ()
    too_many = good.replace("2. Name the CEO.", "2. Name the CEO.\n3. State your event.")
    assert "it lists 3" in review(too_many).problems[0]
    assert "[Screener name]" in review(good.replace("[Screener name]", "Anna")).problems[0]


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
    assert "Missing or inconsistent information:\n1. Upload the cap table." in prompt
    assert "Dear Alpha Bio team," in prompt
    # Only the stated concerns reach the model, not the detailed checklist.
    assert "| 1 | Cap table | Unclear |" not in prompt
    assert calls["reviewers"][0] is not None
    assert summary.path.startswith(
        "storage/generated/application-feedback-runs/insights/"
    )
    text = summary.content()
    assert (
        "New or changed drafts: 1. Unchanged drafts: 0. Without concerns: 1. "
        "Failed: 0." in text
    )
    assert "## New or changed drafts\n\n### Alpha Bio (CODE-1)" in text
    assert "- [Open the application in Dealum](https://app.dealum.com/" in text
    # The draft is a code block, so its line breaks and numbering survive copying.
    assert "```text\nDear Alpha Bio team,\n\n1. Please upload your cap table.\n```" in text
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
    assert "- Alpha Bio (CODE-1): [Open the application in Dealum](https://app.dealum.com/" in text
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


@pytest.fixture
def sent_emails(monkeypatch):
    """Collect the emails the skill would send instead of calling gws."""
    monkeypatch.setenv("SCREENER_EMAILS", "screener@sictic.ch, second@sictic.ch")
    emails = []
    monkeypatch.setattr(
        module,
        "send_html_email",
        lambda recipients, subject, html: emails.append((recipients, subject, html)),
    )
    return emails


@pytest.mark.asyncio
async def test_email_dry_run_saves_the_email_instead_of_sending(feedback_run, sent_emails):
    [summary, preview, draft] = await application_feedback(email="dry-run")

    assert sent_emails == []
    assert preview.path.startswith(summary.directory)
    assert preview.path.endswith(".html")
    text = preview.content()
    assert "Dry run: this email was not sent." in text
    assert text.index("<body") < text.index("Dry run: this email was not sent.")
    assert "To: screener@sictic.ch, second@sictic.ch" in text
    assert "Subject: SICTIC feedback drafts for open applications: 1 new or changed, 0 failed" in text
    assert "Please upload your cap table." in text
    assert draft.dataset == "alpha-bio"


@pytest.mark.asyncio
async def test_email_is_sent_only_when_there_is_news(feedback_run, sent_emails):
    await application_feedback(email="send")
    # The second run finds only unchanged drafts.
    returned = await application_feedback(email="send")

    assert len(sent_emails) == 1
    recipients, subject, html = sent_emails[0]
    assert recipients == ["screener@sictic.ch", "second@sictic.ch"]
    assert subject == "SICTIC feedback drafts for open applications: 1 new or changed, 0 failed"
    assert "Please upload your cap table." in html
    assert [insight.identifier for insight in returned] == ["summary", None]
    assert returned[1].dataset == "alpha-bio"


@pytest.mark.asyncio
async def test_failures_are_emailed_before_the_run_raises(feedback_run, sent_emails):
    reviews, _calls = feedback_run
    await application_feedback(email="send")
    del reviews["CODE-2"]

    with pytest.raises(RuntimeError, match="failed for 1 application"):
        await application_feedback(email="send")

    assert len(sent_emails) == 2
    assert sent_emails[1][1].endswith("0 new or changed, 1 failed")
    assert "review failed for CODE-2" in sent_emails[1][2]


@pytest.mark.asyncio
async def test_email_requires_screener_addresses_before_any_review(feedback_run, monkeypatch):
    _reviews, calls = feedback_run
    monkeypatch.delenv("SCREENER_EMAILS", raising=False)

    with pytest.raises(ValueError, match="SCREENER_EMAILS"):
        await application_feedback(email="dry-run")

    assert calls["reviews"] == []


@pytest.mark.asyncio
async def test_email_failure_raises_after_the_summary_is_saved(feedback_run, monkeypatch):
    monkeypatch.setenv("SCREENER_EMAILS", "screener@sictic.ch")

    def failing_send(_recipients, _subject, _html):
        raise RuntimeError("gws gmail +send failed (exit 2): auth missing")

    monkeypatch.setattr(module, "send_html_email", failing_send)

    with pytest.raises(RuntimeError, match="auth missing"):
        await application_feedback(email="send")

    location = dataset_location_for_domain("application-feedback-runs", "generated")
    summaries = get_storage().list(f"{location.insights_rel}/application-feedback")
    assert len(summaries) == 1
