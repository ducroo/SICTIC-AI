import json

import pytest

from lib.datasets.manifest import IngestionManifest
from lib.datasets.paths import dataset_location_for_domain
from lib.insights import InsightFile
from lib.startups.dealum.manifest import dealum_manifest_path
from lib.startups.identity import canonical_startup_slug
from lib.storage import get_storage
from skills.application_feedback import application_feedback as module
from skills.application_feedback.application_feedback import (
    application_feedback,
)
from skills.skill_registry import SKILL_REGISTRY
from skills.submission_ready.submission_ready import proposed_action, stated_concerns

MODEL = "ollama/test_model:1b"
# Latest checklist and response per startup, as submission_ready returns them.
REVIEWS: dict[str, list[InsightFile]] = {}


def response_report(action, concerns):
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


def save_review(slug, name, action, concerns, run_id="20261031T000000Z"):
    """Save a startup dossier with a submission review and return it as submission_ready would."""
    storage = get_storage()
    location = dataset_location_for_domain(slug, "startups")
    storage.mkdir(location.raw_rel)
    manifest = IngestionManifest(storage, location.parsed_rel)
    manifest.indexed_dataset_revision = "revision-1"
    manifest.save()
    storage.write_text(dealum_manifest_path(slug), json.dumps({
        "startup": name,
        "step": "Application",
        "dealum_url": f"https://app.dealum.com/#/dealroom/1?application={slug}",
    }))
    insights = []
    for identifier, content in (
        ("checklist", "# Checklist\n\n| 1 | Cap table | Unclear |\n"),
        ("response", response_report(action, concerns)),
    ):
        insight = InsightFile(
            dataset=slug,
            skill="submission_ready",
            model=MODEL,
            identifier=identifier,
            subdir=True,
            run_id=run_id,
        )
        insight.save(content)
        insights.append(insight)
    REVIEWS[slug] = insights
    return insights


@pytest.fixture
def drafting(mock_env, monkeypatch):
    """Answer submission_ready from the saved reviews and collect model calls."""
    monkeypatch.setenv("RANKED_LLMS", MODEL)
    monkeypatch.delenv("APPLICATION_FEEDBACK_RECIPIENTS", raising=False)
    REVIEWS.clear()
    calls = {"reviews": [], "prompts": [], "reviewers": []}

    async def fake_submission_ready(startup):
        calls["reviews"].append(startup)
        return list(REVIEWS.get(canonical_startup_slug(startup), []))

    async def fake_generate_markdown(prompt, reviewer=None):
        calls["prompts"].append(prompt)
        calls["reviewers"].append(reviewer)
        return "Dear Alpha Bio team,\n\n1. Please upload your cap table.\n"

    monkeypatch.setattr(module, "submission_ready", fake_submission_ready)
    monkeypatch.setattr(module, "generate_markdown", fake_generate_markdown)
    return calls


@pytest.mark.asyncio
async def test_feedback_uses_the_review_returned_by_submission_ready(drafting):
    save_review("alpha-bio", "Alpha Bio", "Send concerns to startup", ["Upload the cap table."])

    await application_feedback("Alpha Bio")

    assert drafting["reviews"] == ["Alpha Bio"]


@pytest.mark.asyncio
async def test_draft_uses_only_the_concerns_of_the_returned_review(drafting):
    save_review("alpha-bio", "Alpha Bio", "Send concerns to startup", ["Name the CEO."], "20261030T000000Z")
    save_review("alpha-bio", "Alpha Bio", "Send concerns to startup", ["Upload the cap table."])

    [draft] = await application_feedback("Alpha Bio")

    assert draft.path == (
        "storage/startups/alpha-bio/insights/"
        "application-feedback-alpha-bio-test-model-1b.md"
    )
    assert "Please upload your cap table." in draft.content()
    prompt = drafting["prompts"][0]
    assert "Missing or inconsistent information:\n1. Upload the cap table." in prompt
    assert "Name the CEO." not in prompt
    # The greeting uses the name from Dealum, not the dataset slug.
    assert "Dear Alpha Bio team," in prompt
    # Only the stated concerns reach the model, not the detailed checklist.
    assert "| 1 | Cap table | Unclear |" not in prompt
    assert drafting["reviewers"][0] is not None


@pytest.mark.asyncio
async def test_review_without_concerns_gets_no_draft(drafting):
    save_review("beta-labs", "Beta Labs", "Move to Under review", [])

    assert await application_feedback("beta-labs") == []
    assert drafting["prompts"] == []


@pytest.mark.asyncio
async def test_unchanged_concerns_reuse_the_draft_and_changed_ones_redraft(drafting):
    save_review("alpha-bio", "Alpha Bio", "Send concerns to startup", ["Upload the cap table."])
    await application_feedback("alpha-bio")
    await application_feedback("alpha-bio")
    assert len(drafting["prompts"]) == 1

    save_review(
        "alpha-bio", "Alpha Bio", "Send concerns to startup", ["Name the CEO."],
        "20261101T000000Z",
    )
    await application_feedback("alpha-bio")
    assert len(drafting["prompts"]) == 2


@pytest.mark.asyncio
async def test_missing_review_does_nothing(drafting):
    assert await application_feedback("alpha-bio") == []
    assert drafting["prompts"] == []


@pytest.mark.asyncio
async def test_cached_draft_is_returned_without_generating(drafting):
    save_review("alpha-bio", "Alpha Bio", "Send concerns to startup", ["Upload the cap table."])

    [draft] = await application_feedback("alpha-bio")
    [cached] = await application_feedback("alpha-bio")

    assert cached.path == draft.path
    assert len(drafting["prompts"]) == 1


@pytest.mark.asyncio
async def test_configured_signature_signs_the_drafts(drafting, monkeypatch):
    monkeypatch.setenv("SCREENER_SIGNATURE", " Anna  Muster ")
    save_review("alpha-bio", "Alpha Bio", "Send concerns to startup", ["Upload the cap table."])

    await application_feedback("alpha-bio")

    prompt = drafting["prompts"][0]
    assert 'followed by "Anna Muster" and "SICTIC"' in prompt
    assert "{{signature}}" not in prompt
    assert "[Screener name]" not in prompt
    review = drafting["reviewers"][0]
    assert review("1. Upload it.\n\nBest regards,\nAnna Muster\nSICTIC").problems == ()


@pytest.mark.asyncio
async def test_empty_signature_keeps_the_placeholder(drafting, monkeypatch):
    monkeypatch.delenv("SCREENER_SIGNATURE", raising=False)
    save_review("alpha-bio", "Alpha Bio", "Send concerns to startup", ["Upload the cap table."])

    await application_feedback("alpha-bio")

    assert 'followed by "[Screener name]" and "SICTIC"' in drafting["prompts"][0]


@pytest.mark.asyncio
async def test_multiline_qualifications_reach_draft_prompt(drafting):
    save_review("alpha-bio", "Alpha Bio", "Send concerns to startup", [
        "Confirm the cap table.\nInclude outstanding convertible loans.",
    ])

    await application_feedback("alpha-bio")

    assert "Include outstanding convertible loans." in drafting["prompts"][0]


def test_draft_reviewer_rejects_extra_points_and_a_missing_signature():
    review = module._draft_reviewer(2, "[Screener name]")
    good = "Dear team,\n\n1. Upload the cap table.\n2. Name the CEO.\n\nBest regards,\n[Screener name]\nSICTIC"

    assert review(good).problems == ()
    too_many = good.replace("2. Name the CEO.", "2. Name the CEO.\n3. State your event.")
    assert "it lists 3" in review(too_many).problems[0]
    assert "[Screener name]" in review(good.replace("[Screener name]", "Anna")).problems[0]


def test_stated_concerns_reads_both_sections_of_the_response():
    report = response_report("Send concerns to startup", ["Upload the cap table.", "Name the CEO."])

    assert stated_concerns(report) == ([], ["Upload the cap table.", "Name the CEO."])
    assert stated_concerns("# Manually written review\n") == ([], [])


def test_stated_concerns_preserves_continuations_and_nested_lists():
    report = (
        "## Eligibility concerns\n\n"
        "1. Confirm the company's registered office.\n"
        "It must be in Switzerland.\n\n"
        "2. Explain the operating activity.\n"
        "  - Include the location of the team.\n"
        "  1. Describe local operations.\n"
        "## Missing or inconsistent information\n\n"
        "1. Upload the cap table.\n"
        "  Include convertible loans.\n"
        "## Other section\n\n1. Not a concern.\n"
    )
    eligibility, missing = stated_concerns(report)
    assert eligibility == [
        "Confirm the company's registered office.\nIt must be in Switzerland.",
        "Explain the operating activity.\n  - Include the location of the team.\n"
        "  1. Describe local operations.",
    ]
    assert missing == ["Upload the cap table.\n  Include convertible loans."]


def test_proposed_action_reads_the_rendered_response():
    assert proposed_action(response_report("Send concerns to startup", ["x"])) == (
        "Send concerns to startup"
    )
    assert proposed_action("# Manually written review\n") is None


def test_bulk_refresh_drafts_after_the_review_at_stage_application():
    spec = SKILL_REGISTRY["application-feedback"]

    assert spec.func is application_feedback
    assert spec.depends_on == ("submission-ready",)
    assert spec.mandatory_stages == frozenset({"Application", "Under Review"})
    assert spec.mandatory_stages == SKILL_REGISTRY["submission-ready"].mandatory_stages
    assert spec.domains == frozenset({"startups"})
