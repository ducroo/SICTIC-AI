import json
from hashlib import sha256

import pytest

from lib.infrastructure.configuration import config_cache_key
from lib.infrastructure.errors import InfrastructureError, InfrastructureErrorKind
from lib.insights import InsightFile
from lib.storage import get_storage
from skills.application_feedback import application_feedback as module
from skills.application_feedback import delivery
from skills.application_feedback.application_feedback import application_feedback
from tests.skills.test_application_feedback import drafting, save_review  # noqa: F401

JOURNAL = "storage/generated/application-feedback-runs/insights/email-delivery.json"
DEALUM_URL = "https://app.dealum.com/#/dealroom/1?application=alpha-bio"


@pytest.fixture
def sending(drafting, monkeypatch):
    monkeypatch.setenv("APPLICATION_FEEDBACK_RECIPIENTS", "one@sictic.ch, two@sictic.ch")
    sent = []
    monkeypatch.setattr(module, "send_gmail", lambda *args: sent.append(args))
    save_review("alpha-bio", "Alpha Bio", "Send concerns to startup", ["Upload the cap table."])
    return sent


def _key(recipients=("one@sictic.ch", "two@sictic.ch")):
    return config_cache_key({"application": DEALUM_URL, "recipients": sorted(recipients)})


@pytest.mark.asyncio
async def test_concerns_email_puts_the_action_first_then_review_and_draft(sending):
    [draft] = await application_feedback("alpha-bio")

    [(content, recipients, subject)] = sending
    assert recipients == ["one@sictic.ch", "two@sictic.ch"]
    assert subject == "SICTIC screening: Alpha Bio: Send concerns to startup"
    assert content.startswith("# Alpha Bio: Send concerns to startup\n\n")
    assert f"[Open the application in Dealum]({DEALUM_URL})" in content
    # The review's headings sit below the email title.
    assert "## Proposed action" in content
    assert "### Missing or inconsistent information\n\n1. Upload the cap table." in content
    assert content.index("## Proposed action") < content.index("## Reply to the startup")
    # The draft is a code block, so its line breaks and numbering survive copying.
    assert f"```text\n{draft.content().strip()}\n```" in content
    assert "replace [Screener name]" in content
    assert [item.path for item in await application_feedback("alpha-bio")] == [draft.path]
    assert len(sending) == 1


@pytest.mark.asyncio
async def test_progression_is_emailed_with_review_and_without_draft(sending, drafting):
    save_review("alpha-bio", "Alpha Bio", "Move to Under review", [])

    assert await application_feedback("alpha-bio") == []

    [(content, _recipients, subject)] = sending
    assert subject == "SICTIC screening: Alpha Bio: Move to Under review"
    assert content.startswith("# Alpha Bio: Move to Under review\n\n")
    assert f"[Open the application in Dealum]({DEALUM_URL})" in content
    assert "carry out the proposed action in Dealum" in content
    assert "- Proposed action: Move to Under review" in content
    assert "Reply to the startup" not in content
    assert drafting["prompts"] == []
    await application_feedback("alpha-bio")
    assert len(sending) == 1


@pytest.mark.asyncio
async def test_changed_decision_is_emailed_again(sending):
    await application_feedback("alpha-bio")
    save_review("alpha-bio", "Alpha Bio", "Move to Under review", [], "20261101T000000Z")

    await application_feedback("alpha-bio")

    assert len(sending) == 2
    assert sending[-1][2] == "SICTIC screening: Alpha Bio: Move to Under review"


@pytest.mark.asyncio
async def test_other_startup_is_a_separate_email(sending):
    save_review("beta-bio", "Beta Bio", "Send concerns to startup", ["Name the CEO."])
    await application_feedback("alpha-bio")
    await application_feedback("beta-bio")
    assert len(sending) == 2
    assert [item[2] for item in sending] == [
        "SICTIC screening: Alpha Bio: Send concerns to startup",
        "SICTIC screening: Beta Bio: Send concerns to startup",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["off", "dry-run"])
async def test_preview_does_not_consume_delivery(sending, mode):
    [draft] = await application_feedback("alpha-bio", email=mode)
    assert draft.content()
    assert sending == []
    assert not get_storage().exists(JOURNAL)
    await application_feedback("alpha-bio")
    assert len(sending) == 1


@pytest.mark.asyncio
async def test_empty_recipients_saves_without_delivery(sending, monkeypatch):
    monkeypatch.setenv("APPLICATION_FEEDBACK_RECIPIENTS", "")
    [draft] = await application_feedback("alpha-bio")
    assert draft.content()
    assert sending == []
    assert not get_storage().exists(JOURNAL)


@pytest.mark.asyncio
async def test_recipient_order_and_duplicates_do_not_resend_but_changes_do(sending, monkeypatch):
    await application_feedback("alpha-bio")
    monkeypatch.setenv("APPLICATION_FEEDBACK_RECIPIENTS", "two@sictic.ch,one@sictic.ch,one@sictic.ch")
    await application_feedback("alpha-bio")
    assert len(sending) == 1
    monkeypatch.setenv("APPLICATION_FEEDBACK_RECIPIENTS", "new@sictic.ch")
    await application_feedback("alpha-bio")
    assert len(sending) == 2
    assert sending[-1][1] == ["new@sictic.ch"]


@pytest.mark.asyncio
async def test_changed_manual_draft_delivered_once(sending):
    await application_feedback("alpha-bio")
    manual = InsightFile(dataset="alpha-bio", skill="application_feedback", model="manual")
    manual.save("Dear team,\n\n1. Please clarify IP ownership.\n")
    [returned] = await application_feedback("alpha-bio")
    await application_feedback("alpha-bio")
    assert returned.path == manual.path
    assert len(sending) == 2
    assert "Please clarify IP ownership." in sending[-1][0]


@pytest.mark.asyncio
async def test_changed_generated_content_delivered(sending, monkeypatch):
    await application_feedback("alpha-bio")
    save_review("alpha-bio", "Alpha Bio", "Send concerns to startup", ["Name the CEO."], "20261101T000000Z")
    async def changed(*args, **kwargs):
        return "Dear Alpha Bio team,\n\n1. Name the CEO.\n"
    monkeypatch.setattr(module, "generate_markdown", changed)
    await application_feedback("alpha-bio")
    assert len(sending) == 2
    assert "1. Name the CEO." in sending[-1][0]


@pytest.mark.asyncio
async def test_uncertain_delivery_holds_only_affected_startup(sending, monkeypatch):
    sender = module.send_gmail
    def timeout(*args):
        raise InfrastructureError("timeout", provider="gws", operation="send_email",
                                  kind=InfrastructureErrorKind.TIMEOUT)
    monkeypatch.setattr(module, "send_gmail", timeout)
    with pytest.raises(InfrastructureError):
        await application_feedback("alpha-bio")
    monkeypatch.setattr(module, "send_gmail", sender)
    assert len(await application_feedback("alpha-bio")) == 1
    assert sending == []
    save_review("beta", "Beta", "Send concerns to startup", ["Name the CEO."])
    await application_feedback("beta")
    assert len(sending) == 1
    assert sending[0][2] == "SICTIC screening: Beta: Send concerns to startup"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [
    InfrastructureErrorKind.CONFIGURATION,
    InfrastructureErrorKind.AUTHENTICATION,
])
async def test_failures_before_gmail_are_sent_on_a_later_run(sending, monkeypatch, kind):
    sender = module.send_gmail
    def not_sent(*args):
        raise InfrastructureError("gws not ready", provider="gws", operation="send_email",
                                  kind=kind)
    monkeypatch.setattr(module, "send_gmail", not_sent)
    with pytest.raises(InfrastructureError):
        await application_feedback("alpha-bio")
    assert json.loads(get_storage().read_text(JOURNAL)) == {}
    monkeypatch.setattr(module, "send_gmail", sender)
    await application_feedback("alpha-bio")
    assert len(sending) == 1


@pytest.mark.asyncio
async def test_failed_acknowledgement_does_not_duplicate_send(sending, monkeypatch):
    writer = delivery.write_if_changed
    def fail_sent(storage, path, content):
        if any(entry["status"] == "sent" for entry in json.loads(content).values()):
            raise OSError("receipt save failed")
        writer(storage, path, content)
    monkeypatch.setattr(delivery, "write_if_changed", fail_sent)
    with pytest.raises(OSError):
        await application_feedback("alpha-bio")
    monkeypatch.setattr(delivery, "write_if_changed", writer)
    await application_feedback("alpha-bio")
    assert len(sending) == 1


@pytest.mark.asyncio
async def test_invalid_journal_fails_closed(sending):
    get_storage().write_text(JOURNAL, '{"bad": {}}')
    with pytest.raises(ValueError):
        await application_feedback("alpha-bio")
    assert sending == []


@pytest.mark.asyncio
async def test_receipt_tracks_the_complete_email(sending):
    [draft] = await application_feedback("alpha-bio")

    [(content, _recipients, _subject)] = sending
    receipts = json.loads(get_storage().read_text(JOURNAL))
    assert receipts == {_key(): {
        "status": "sent",
        "digest": sha256(content.encode("utf-8")).hexdigest(),
        "summary": draft.path,
    }}


@pytest.mark.asyncio
async def test_draft_only_receipts_send_each_open_decision_once(sending):
    [draft] = await application_feedback("alpha-bio", email="off")
    # Earlier versions tracked only the draft, not the complete email.
    get_storage().write_text(JOURNAL, json.dumps({_key(): {
        "status": "sent", "digest": sha256(draft.content().encode()).hexdigest(),
        "summary": draft.path}}))

    await application_feedback("alpha-bio")
    await application_feedback("alpha-bio")

    assert len(sending) == 1


@pytest.mark.asyncio
async def test_review_failure_never_sends(sending, monkeypatch):
    async def failed(*args, **kwargs):
        raise RuntimeError("Submission-ready failed for 1 startup(s)")
    monkeypatch.setattr(module, "submission_ready", failed)
    with pytest.raises(RuntimeError, match="Submission-ready failed"):
        await application_feedback("alpha-bio")
    assert sending == []


@pytest.mark.asyncio
async def test_missing_review_never_sends(sending, drafting):
    assert await application_feedback("unknown") == []
    assert sending == []
    assert drafting["prompts"] == []
