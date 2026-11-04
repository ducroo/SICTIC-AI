import json

import pytest

from lib.datasets.paths import dataset_location_for_domain
from lib.infrastructure.errors import InfrastructureError, InfrastructureErrorKind
from lib.insights import InsightFile
from lib.storage import get_storage
from skills.application_feedback import application_feedback as feedback_module
from skills.application_feedback.application_feedback import application_feedback
from skills.distribution_policy import distribution_policy as module
from skills.distribution_policy.distribution_policy import (
    open_applications,
    requested_insights,
    screener_feedback,
)
from tests.skills.test_application_feedback import MODEL, save_review

JOURNAL = "storage/generated/application-feedback-runs/insights/email-delivery.json"


def _application(name, step, application_id):
    return {"id": application_id, "name": name, "code": f"CODE-{application_id}", "step": step}


class FakeAdapter:
    dealroom_id = "test-room"

    def is_configured(self):
        return True


@pytest.fixture
def screening(mock_env, monkeypatch):
    """Open applications in Dealum with reviews stored by a nightly bulk refresh."""
    monkeypatch.setenv("RANKED_LLMS", MODEL)
    monkeypatch.setenv("SCREENER_EMAILS", "screener@sictic.ch, second@sictic.ch")
    monkeypatch.setattr(module, "DealumAdapter", FakeAdapter)
    applications = [
        _application("Beta Labs", "Application", 2),
        _application("Alpha Bio", "Application", 1),
        _application("Gamma Robotics", "Under Review", 3),
        _application("Delta Unknown", "Some new stage", 4),
    ]
    monkeypatch.setattr(module, "list_applications", lambda _adapter: applications)
    drafts = {"Alpha Bio": "Dear Alpha Bio team,\n\n1. Please upload your cap table.\n"}

    async def fake_generate_markdown(prompt, reviewer=None):
        name = next(name for name in drafts if f"Dear {name} team" in prompt)
        return drafts[name]

    monkeypatch.setattr(feedback_module, "generate_markdown", fake_generate_markdown)
    save_review("alpha-bio", "Alpha Bio", "Send concerns to startup", ["Upload the cap table."])
    save_review("beta-labs", "Beta Labs", "Move to Under review", [])
    return applications, drafts


@pytest.fixture
def sent_emails(monkeypatch):
    """Collect the emails instead of sending them through gws."""
    emails = []
    monkeypatch.setattr(
        module,
        "send_gmail",
        lambda markdown, recipients, subject: emails.append((recipients, subject, markdown)),
    )
    return emails


async def _draft_all():
    for startup in ("alpha-bio", "beta-labs"):
        await application_feedback(startup)


def test_open_applications_use_each_startups_latest_application():
    applications = [
        _application("Beta", "Application", 2),
        _application("alpha", "application", 1),
        # Gamma's newer application is already under review.
        {"id": 7, "name": "Gamma", "code": "CODE-7", "step": "Application", "createDate": "2026-01-01"},
        {"id": 8, "name": "Gamma", "code": "CODE-8", "step": "Under Review", "createDate": "2026-06-01"},
        _application("Delta", None, 4),
    ]

    selected = open_applications(applications, FakeAdapter())

    assert [(entry.startup, entry.code, entry.dataset_slug) for entry in selected] == [
        ("alpha", "CODE-1", "alpha"), ("Beta", "CODE-2", "beta"),
    ]
    assert selected[0].dealum_url.startswith("https://app.dealum.com/")


@pytest.mark.asyncio
async def test_summary_lists_drafts_and_applications_without_concerns(screening):
    await _draft_all()

    [summary] = screener_feedback()

    assert summary.path.startswith("storage/generated/application-feedback-runs/insights/")
    text = summary.content()
    assert "Open applications in the Dealum stage \"Application\": 2." in text
    assert "## New, changed or undelivered drafts\n\n### Alpha Bio (CODE-1)" in text
    assert "- [Open the application in Dealum](https://app.dealum.com/" in text
    # The draft is a code block, so its line breaks and numbering survive copying.
    assert "```text\nDear Alpha Bio team,\n\n1. Please upload your cap table.\n```" in text
    assert "- Beta Labs (CODE-2): Move to Under review." in text
    assert "Gamma Robotics" not in text


@pytest.mark.asyncio
async def test_application_without_review_or_draft_is_not_ready(screening):
    applications, _drafts = screening
    applications.append(_application("Epsilon", "Application", 5))
    get_storage().mkdir(dataset_location_for_domain("epsilon", "startups").raw_rel)
    # Alpha Bio has concerns, but bulk refresh did not draft it.
    await application_feedback("beta-labs")

    [summary] = screener_feedback()

    text = summary.content()
    assert "Not ready: 2." in text
    assert "- Alpha Bio (CODE-1): The review has concerns but no current draft" in text
    assert "- Epsilon (CODE-5): No submission review found for 'epsilon'" in text


@pytest.mark.asyncio
async def test_email_dry_run_saves_the_email_instead_of_sending(screening, sent_emails):
    await _draft_all()

    [summary, preview] = screener_feedback(email="dry-run")

    assert sent_emails == []
    assert preview.path.startswith(summary.directory)
    text = preview.content()
    assert text.index("<body") < text.index("Dry run: this email was not sent.")
    assert "To: screener@sictic.ch, second@sictic.ch" in text
    assert "1 new, changed or undelivered, 0 not ready" in text
    assert "Please upload your cap table." in text


@pytest.mark.asyncio
async def test_email_is_sent_only_when_there_is_news(screening, sent_emails):
    await _draft_all()
    screener_feedback(email="send")
    screener_feedback(email="send")

    assert len(sent_emails) == 1
    recipients, subject, markdown = sent_emails[0]
    assert recipients == ["screener@sictic.ch", "second@sictic.ch"]
    assert subject == (
        "SICTIC feedback drafts for open applications: "
        "1 new, changed or undelivered, 0 not ready"
    )
    assert "Please upload your cap table." in markdown


@pytest.mark.asyncio
async def test_email_requires_screener_addresses(screening, monkeypatch):
    monkeypatch.delenv("SCREENER_EMAILS", raising=False)

    with pytest.raises(ValueError, match="SCREENER_EMAILS"):
        screener_feedback(email="dry-run")
    assert screener_feedback(email="off")


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_mode", ["off", "dry-run"])
async def test_preview_or_off_does_not_consume_delivery(screening, sent_emails, initial_mode):
    await _draft_all()
    screener_feedback(email=initial_mode)
    screener_feedback(email="send")
    screener_feedback(email="send")

    assert len(sent_emails) == 1
    assert "Please upload your cap table." in sent_emails[0][2]


@pytest.mark.asyncio
async def test_missing_gws_can_be_retried_on_a_later_run(screening, sent_emails, monkeypatch):
    await _draft_all()
    sender = module.send_gmail

    def missing_gws(*_args):
        raise InfrastructureError("gws not found", provider="gws", operation="send_email",
                                  kind=InfrastructureErrorKind.CONFIGURATION)

    monkeypatch.setattr(module, "send_gmail", missing_gws)
    with pytest.raises(InfrastructureError, match="gws not found"):
        screener_feedback(email="send")
    monkeypatch.setattr(module, "send_gmail", sender)
    screener_feedback(email="send")
    assert len(sent_emails) == 1
    assert "Please upload your cap table." in sent_emails[0][2]


@pytest.mark.asyncio
async def test_uncertain_delivery_holds_back_only_that_draft(screening, sent_emails, monkeypatch):
    applications, drafts = screening
    await _draft_all()
    sender = module.send_gmail

    def timeout(*_args):
        raise InfrastructureError("timed out", provider="gws", operation="send_email",
                                  kind=InfrastructureErrorKind.TIMEOUT)

    monkeypatch.setattr(module, "send_gmail", timeout)
    with pytest.raises(InfrastructureError, match="timed out"):
        screener_feedback(email="send")

    # The next night a new application arrives; the run continues.
    monkeypatch.setattr(module, "send_gmail", sender)
    applications.append(_application("Zeta Energy", "Application", 6))
    drafts["Zeta Energy"] = "Dear Zeta Energy team,\n\n1. Please name the CEO.\n"
    save_review("zeta-energy", "Zeta Energy", "Send concerns to startup", ["Name the CEO."])
    await application_feedback("zeta-energy")
    [summary] = screener_feedback(email="send")

    assert len(sent_emails) == 1
    markdown = sent_emails[0][2]
    assert "Please name the CEO." in markdown
    # The uncertain draft is listed, but not sent again.
    assert "Please upload your cap table." not in markdown
    assert "## Delivery uncertain" in markdown
    assert "- Alpha Bio (CODE-1):" in markdown
    assert "Delivery uncertain: 1." in summary.content()


@pytest.mark.asyncio
async def test_changed_recipients_receive_stored_draft(screening, sent_emails, monkeypatch):
    await _draft_all()
    screener_feedback(email="send")
    monkeypatch.setenv("SCREENER_EMAILS", "new@sictic.ch")
    screener_feedback(email="send")

    assert len(sent_emails) == 2
    assert sent_emails[1][0] == ["new@sictic.ch"]
    assert "Please upload your cap table." in sent_emails[1][2]


@pytest.mark.asyncio
async def test_recipient_order_does_not_resend(screening, sent_emails, monkeypatch):
    await _draft_all()
    screener_feedback(email="send")
    monkeypatch.setenv("SCREENER_EMAILS", "second@sictic.ch, screener@sictic.ch")
    screener_feedback(email="send")

    assert len(sent_emails) == 1


@pytest.mark.asyncio
async def test_changed_manual_draft_is_delivered(screening, sent_emails):
    await _draft_all()
    screener_feedback(email="send")
    InsightFile(dataset="alpha-bio", skill="application_feedback", model="manual").save(
        "Dear team,\n\n1. Please clarify the ownership of the IP.\n",
    )
    screener_feedback(email="send")
    screener_feedback(email="send")

    assert len(sent_emails) == 2
    assert "ownership of the IP" in sent_emails[1][2]


@pytest.mark.asyncio
async def test_failed_receipt_save_does_not_allow_duplicate_send(screening, sent_emails, monkeypatch):
    from skills.distribution_policy import delivery

    await _draft_all()
    writer = delivery.write_if_changed

    def fail_acknowledgement(storage, path, content):
        if any(entry["status"] == "sent" for entry in json.loads(content).values()):
            raise OSError("receipt disk write failed")
        writer(storage, path, content)

    monkeypatch.setattr(delivery, "write_if_changed", fail_acknowledgement)
    with pytest.raises(OSError, match="receipt disk write failed"):
        screener_feedback(email="send")
    assert len(sent_emails) == 1
    monkeypatch.setattr(delivery, "write_if_changed", writer)
    [summary] = screener_feedback(email="send")
    assert len(sent_emails) == 1
    assert "Delivery uncertain: 1." in summary.content()


@pytest.mark.asyncio
async def test_invalid_receipt_state_fails_closed(screening, sent_emails):
    await _draft_all()
    get_storage().write_text(JOURNAL, '{"bad": {}}')

    with pytest.raises(ValueError):
        screener_feedback(email="send")
    assert sent_emails == []


def test_requested_insight_is_emailed_in_full_to_the_requester(mock_env, sent_emails):
    path = "storage/startups/alpha-bio/insights/startup-profile-alpha-bio-test-model-1b.md"
    get_storage().write_text(path, "# Startup profile: Alpha Bio\n\nFull profile text.\n")

    requested_insights([path], " analyst@sictic.ch ", requester_agreed=True)

    assert sent_emails == [(
        ["analyst@sictic.ch"],
        "SICTIC insight: Startup profile: Alpha Bio",
        "# Startup profile: Alpha Bio\n\nFull profile text.\n",
    )]


@pytest.mark.parametrize(
    ("insights", "requester", "agreed", "message"),
    [
        (["a.md"], "analyst@sictic.ch", False, "agreed"),
        (["a.md"], "one@sictic.ch, two@sictic.ch", True, "exactly one"),
        ([], "analyst@sictic.ch", True, "at least one"),
        (["profile.md", "data.json"], "analyst@sictic.ch", True, "Only Markdown"),
        (["missing.md"], "analyst@sictic.ch", True, "not found"),
    ],
)
def test_requested_insights_are_checked_before_sending(
    mock_env, sent_emails, insights, requester, agreed, message,
):
    get_storage().write_text("profile.md", "# Profile\n")

    with pytest.raises(ValueError, match=message):
        requested_insights(insights, requester, requester_agreed=agreed)
    assert sent_emails == []
