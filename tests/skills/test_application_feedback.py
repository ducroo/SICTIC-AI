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
    review = module._draft_reviewer(2, "[Screener name]")
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
        "New, changed or undelivered drafts: 1. Unchanged drafts: 0. Without concerns: 1. "
        "Failed: 0." in text
    )
    assert "## New, changed or undelivered drafts\n\n### Alpha Bio (CODE-1)" in text
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
    assert "New, changed or undelivered drafts: 0. Unchanged drafts: 1." in text
    assert "## New, changed or undelivered drafts" not in text
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
        "New, changed or undelivered drafts: 1. Unchanged drafts: 0. Without concerns: 0. "
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
    assert "Subject: SICTIC feedback drafts for open applications: 1 new, changed or undelivered, 0 failed" in text
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
    assert subject == "SICTIC feedback drafts for open applications: 1 new, changed or undelivered, 0 failed"
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
    assert sent_emails[1][1].endswith("0 new, changed or undelivered, 1 failed")
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


@pytest.mark.asyncio
async def test_configured_signature_signs_the_drafts(feedback_run, monkeypatch):
    _reviews, calls = feedback_run
    monkeypatch.setenv("SCREENER_SIGNATURE", " Anna  Muster ")

    [summary, _draft] = await application_feedback()

    prompt = calls["prompts"][0]
    assert 'followed by "Anna Muster" and "SICTIC"' in prompt
    assert "{{signature}}" not in prompt
    assert "[Screener name]" not in prompt
    review = calls["reviewers"][0]
    assert review("1. Upload it.\n\nBest regards,\nAnna Muster\nSICTIC").problems == ()
    assert "[Screener name]" not in summary.content()


@pytest.mark.asyncio
async def test_empty_signature_keeps_the_placeholder(feedback_run, monkeypatch):
    _reviews, calls = feedback_run
    monkeypatch.delenv("SCREENER_SIGNATURE", raising=False)

    [summary, _draft] = await application_feedback()

    assert 'followed by "[Screener name]" and "SICTIC"' in calls["prompts"][0]
    assert "replace [Screener name] and paste it" in summary.content()


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_mode", ["off", "dry-run"])
async def test_preview_or_off_does_not_consume_delivery(feedback_run, sent_emails, initial_mode):
    _reviews, calls = feedback_run
    await application_feedback(email=initial_mode)
    await application_feedback(email="send")
    await application_feedback(email="send")

    assert len(calls["prompts"]) == 1
    assert len(sent_emails) == 1
    assert "Please upload your cap table." in sent_emails[0][2]


@pytest.mark.asyncio
async def test_missing_gws_can_be_retried_on_a_later_run(feedback_run, sent_emails, monkeypatch):
    from lib.infrastructure.errors import InfrastructureError, InfrastructureErrorKind

    sender = module.send_html_email

    def missing_gws(*_args):
        raise InfrastructureError("gws not found", provider="gws", operation="send_email",
                                  kind=InfrastructureErrorKind.CONFIGURATION)

    monkeypatch.setattr(module, "send_html_email", missing_gws)
    with pytest.raises(InfrastructureError, match="gws not found"):
        await application_feedback(email="send")
    monkeypatch.setattr(module, "send_html_email", sender)
    await application_feedback(email="send")
    assert len(sent_emails) == 1
    assert "Please upload your cap table." in sent_emails[0][2]


@pytest.mark.asyncio
async def test_uncertain_send_remains_visible_and_is_not_retried(feedback_run, sent_emails, monkeypatch):
    from lib.infrastructure.errors import InfrastructureError, InfrastructureErrorKind

    attempts = []

    def timeout(*args):
        attempts.append(args)
        raise InfrastructureError("timed out", provider="gws", operation="send_email",
                                  kind=InfrastructureErrorKind.TIMEOUT)

    monkeypatch.setattr(module, "send_html_email", timeout)
    with pytest.raises(InfrastructureError, match="timed out"):
        await application_feedback(email="send")
    with pytest.raises(RuntimeError, match="delivery for Alpha Bio is uncertain"):
        await application_feedback(email="send")
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_changed_recipients_receive_cached_draft(feedback_run, sent_emails, monkeypatch):
    await application_feedback(email="send")
    monkeypatch.setenv("SCREENER_EMAILS", "new@sictic.ch")
    await application_feedback(email="send")
    assert len(sent_emails) == 2
    assert sent_emails[1][0] == ["new@sictic.ch"]
    assert "Please upload your cap table." in sent_emails[1][2]


@pytest.mark.asyncio
async def test_recipient_order_does_not_resend(feedback_run, sent_emails, monkeypatch):
    await application_feedback(email="send")
    monkeypatch.setenv("SCREENER_EMAILS", "second@sictic.ch, screener@sictic.ch")
    await application_feedback(email="send")
    assert len(sent_emails) == 1


@pytest.mark.asyncio
async def test_changed_manual_draft_is_delivered_without_generation(feedback_run, sent_emails):
    _reviews, calls = feedback_run
    [_, draft] = await application_feedback(email="send")
    manual = InsightFile(dataset=draft.dataset, skill="application_feedback", model="manual")
    manual.save("Dear team,\n\n1. Please clarify the ownership of the IP.\n")
    await application_feedback(email="send")
    await application_feedback(email="send")
    assert len(sent_emails) == 2
    assert "ownership of the IP" in sent_emails[1][2]
    assert len(calls["prompts"]) == 1


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


@pytest.mark.asyncio
async def test_multiline_qualifications_reach_draft_prompt(feedback_run):
    reviews, calls = feedback_run
    reviews["CODE-1"] = ("Send concerns to startup", [
        "Confirm the cap table.\nInclude outstanding convertible loans.",
    ])
    await application_feedback()
    assert "Include outstanding convertible loans." in calls["prompts"][0]


@pytest.mark.asyncio
async def test_failed_receipt_save_does_not_allow_duplicate_send(feedback_run, sent_emails, monkeypatch):
    import json
    from skills.application_feedback import delivery

    writer = delivery.write_if_changed

    def fail_acknowledgement(storage, path, content):
        if any(entry["status"] == "sent" for entry in json.loads(content).values()):
            raise OSError("receipt disk write failed")
        writer(storage, path, content)

    monkeypatch.setattr(delivery, "write_if_changed", fail_acknowledgement)
    with pytest.raises(OSError, match="receipt disk write failed"):
        await application_feedback(email="send")
    assert len(sent_emails) == 1
    monkeypatch.setattr(delivery, "write_if_changed", writer)
    with pytest.raises(RuntimeError, match="is uncertain"):
        await application_feedback(email="send")
    assert len(sent_emails) == 1


@pytest.mark.asyncio
async def test_invalid_receipt_state_fails_closed(feedback_run, sent_emails):
    location = dataset_location_for_domain("application-feedback-runs", "generated")
    get_storage().write_text(f"{location.insights_rel}/email-delivery.json", '{"bad": {}}')
    with pytest.raises(ValueError):
        await application_feedback(email="send")
    assert sent_emails == []
