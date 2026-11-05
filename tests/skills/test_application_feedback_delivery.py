import json
from hashlib import sha256

import pytest

from lib.datasets.manifest import IngestionManifest
from lib.datasets.paths import dataset_location_for_domain
from lib.infrastructure.configuration import config_cache_key, load_repository_config
from lib.infrastructure.errors import InfrastructureError, InfrastructureErrorKind
from lib.insights import InsightFile
from lib.startups.dealum.manifest import dealum_manifest_path
from lib.storage import get_storage
from skills.application_feedback import application_feedback as module
from skills.application_feedback import delivery
from skills.application_feedback.application_feedback import application_feedback
from skills.submission_ready.submission_ready import latest_response
from tests.skills.test_application_feedback import MODEL, drafting, save_review

JOURNAL = "storage/generated/application-feedback-runs/insights/email-delivery.json"


@pytest.fixture
def sending(drafting, monkeypatch):
    monkeypatch.setenv("APPLICATION_FEEDBACK_RECIPIENTS", "one@sictic.ch, two@sictic.ch")
    sent = []
    monkeypatch.setattr(module, "send_gmail", lambda *args: sent.append(args))
    save_review("alpha-bio", "Alpha Bio", "Send concerns to startup", ["Upload the cap table."])
    return sent


@pytest.mark.asyncio
async def test_one_email_per_startup_to_all_recipients_and_full_insight_returned(sending):
    [draft] = await application_feedback("alpha-bio")
    assert sending == [(draft.content(), ["one@sictic.ch", "two@sictic.ch"],
                        "SICTIC application feedback: Alpha Bio")]
    assert [item.path for item in await application_feedback("alpha-bio")] == [draft.path]
    assert len(sending) == 1


@pytest.mark.asyncio
async def test_other_startup_is_a_separate_email(sending):
    save_review("beta-bio", "Beta Bio", "Send concerns to startup", ["Name the CEO."])
    await application_feedback("alpha-bio")
    await application_feedback("beta-bio")
    assert len(sending) == 2
    assert [item[2] for item in sending] == [
        "SICTIC application feedback: Alpha Bio", "SICTIC application feedback: Beta Bio"]


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
    assert sending[-1][0] == manual.content()


@pytest.mark.asyncio
async def test_changed_generated_content_delivered(sending, monkeypatch):
    await application_feedback("alpha-bio")
    save_review("alpha-bio", "Alpha Bio", "Send concerns to startup", ["Name the CEO."], "20261101T000000Z")
    async def changed(*args, **kwargs):
        return "Dear Alpha Bio team,\n\n1. Name the CEO.\n"
    monkeypatch.setattr(module, "generate_markdown", changed)
    await application_feedback("alpha-bio")
    assert len(sending) == 2
    assert "Name the CEO" in sending[-1][0]


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
    assert sending[0][2].endswith("Beta")


@pytest.mark.asyncio
async def test_missing_gws_can_be_retried(sending, monkeypatch):
    sender = module.send_gmail
    def missing(*args):
        raise InfrastructureError("gws not found", provider="gws", operation="send_email",
                                  kind=InfrastructureErrorKind.CONFIGURATION)
    monkeypatch.setattr(module, "send_gmail", missing)
    with pytest.raises(InfrastructureError):
        await application_feedback("alpha-bio")
    monkeypatch.setattr(module, "send_gmail", sender)
    await application_feedback("alpha-bio")
    assert len(sending) == 1


@pytest.mark.asyncio
async def test_gws_login_failure_is_sent_on_a_later_run(sending, monkeypatch):
    sender = module.send_gmail
    def login_failed(*args):
        raise InfrastructureError("Gmail auth failed", provider="gws", operation="send_email",
                                  kind=InfrastructureErrorKind.AUTHENTICATION)
    monkeypatch.setattr(module, "send_gmail", login_failed)
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
async def test_existing_receipts_prevent_resending_after_migration(sending):
    [draft] = await application_feedback("alpha-bio", email="off")
    key = config_cache_key({"application": "Alpha Bio", "recipients": ["one@sictic.ch", "two@sictic.ch"]})
    get_storage().write_text(JOURNAL, json.dumps({key: {
        "status": "sent", "digest": sha256(draft.content().encode()).hexdigest(),
        "summary": "storage/generated/application-feedback-runs/insights/old-summary.md"}}))
    await application_feedback("alpha-bio")
    assert sending == []


@pytest.mark.asyncio
@pytest.mark.parametrize("stale", ["revision", "config", "stage", "missing-metadata", "partial-run"])
async def test_stale_review_does_not_generate_or_send_even_with_cached_manual_draft(sending, drafting, monkeypatch, stale):
    [draft] = await application_feedback("alpha-bio", email="off")
    InsightFile(dataset="alpha-bio", skill="application_feedback", model="manual").save(draft.content())
    count = len(drafting["prompts"])
    if stale == "revision":
        location = dataset_location_for_domain("alpha-bio", "startups")
        manifest = IngestionManifest.load(get_storage(), location.parsed_rel)
        manifest.indexed_dataset_revision = "revision-2"
        manifest.save()
    elif stale == "config":
        from skills.submission_ready import submission_ready as screening
        real_config = screening.load_repository_config
        def changed(*sections):
            config = real_config(*sections)
            return {**config, "policy": config["policy"] + "\nNew policy."} if sections == ("submission_ready",) else config
        monkeypatch.setattr(screening, "load_repository_config", changed)
    elif stale == "stage":
        get_storage().write_text(dealum_manifest_path("alpha-bio"), json.dumps({"startup": "Alpha Bio", "step": "Under Review"}))
    elif stale == "missing-metadata":
        latest_response("alpha-bio").config_key = "wrong"
        response = latest_response("alpha-bio")
        response.save(response.content())
    else:
        from lib.batch_audit.checklist import parse_checklist
        config = load_repository_config("submission_ready")
        audit = InsightFile(dataset="alpha-bio", skill="batch_audit", model=MODEL,
                            identifier=f"submission_ready-{parse_checklist(config['checklist']).title}",
                            subdir=True, extension="json").find(selection="any")
        updated = json.loads(audit.content())
        updated["chapters"][0]["checks"][0]["result"]["rationale"] = "Updated audit evidence."
        audit.save(json.dumps(updated))
        InsightFile(dataset="alpha-bio", skill="submission_ready", model=MODEL,
                    identifier="checklist", subdir=True, run_id="20261102T000000Z").save("# Partial run\n")
    assert await application_feedback("alpha-bio") == []
    assert len(drafting["prompts"]) == count
    assert sending == []


@pytest.mark.asyncio
async def test_partial_report_does_not_block_a_still_fresh_cached_review(sending):
    InsightFile(dataset="alpha-bio", skill="submission_ready", model=MODEL,
                identifier="checklist", subdir=True, run_id="20261102T000000Z").save("# Partial run\n")
    assert len(await application_feedback("alpha-bio")) == 1
    assert len(sending) == 1


@pytest.mark.asyncio
async def test_sync_failure_never_sends(sending, monkeypatch):
    async def failed(*args, **kwargs):
        raise RuntimeError("sync failed")
    monkeypatch.setattr(module, "sync_datasets", failed)
    with pytest.raises(RuntimeError, match="sync failed"):
        await application_feedback("alpha-bio")
    assert sending == []


@pytest.mark.asyncio
async def test_missing_and_no_concerns_never_send(sending, drafting):
    assert await application_feedback("unknown") == []
    save_review("alpha-bio", "Alpha Bio", "Move to Under review", [])
    assert await application_feedback("alpha-bio") == []
    assert sending == []
    assert drafting["prompts"] == []
