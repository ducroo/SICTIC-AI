"""Acquisition lifecycle contracts, isolated from live providers and dossiers."""

import asyncio
import importlib
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from typer.testing import CliRunner

from lib.storage import get_storage
from lib.infrastructure.errors import InfrastructureError, InfrastructureErrorKind
from lib.infrastructure.companyresearch import CompanyResearchError
from skills.import_companyresearch import import_companyresearch

workflow = importlib.import_module("skills.import_companyresearch.import_companyresearch")
identity = importlib.import_module("skills.import_companyresearch.identity")
UID = "CHE-123.456.789"
OTHER = "CHE-987.654.321"


def report(uid=UID):
    return {"companyIdentity": {"uid": uid, "legalName": "Example AG"},
            "overview": {"summary": "An example company"},
            "sources": [{"id": "source-1", "url": "https://example.org/evidence"}],
            "evidence": [{"fieldPath": "/overview", "sourceIds": ["source-1"]}]}


class Adapter:
    def __init__(self, status="queued"):
        self.status = status
        self.posts = []
        self.gets = []
        self.queries = []
        self.downloads = []
        self.ids = {}
        self.fail_post = False
        self.fail_download = False

    def value(self, uid, key):
        return {"companyUid": uid, "requestId": key, "status": self.status,
                "runId": "run-1" if self.status == "succeeded" else None,
                "error": {"code": "research_failed"} if self.status == "failed" else None}

    async def submit(self, uid, key):
        self.posts.append((uid, key))
        self.ids[key] = uid
        if self.fail_post:
            self.fail_post = False
            raise TimeoutError("Connection lost after acceptance")
        return self.value(uid, key)

    async def receipt(self, request_id):
        self.gets.append(request_id)
        return self.value(self.ids[request_id], request_id)

    async def report(self, uid, run_id):
        self.downloads.append((uid, run_id))
        if self.fail_download:
            raise TimeoutError("download failed")
        return report(uid)

    async def suggestions(self, query):
        self.queries.append(query)
        return [{"uid": UID, "name": "Example AG", "legalSeat": "Zurich", "status": "active"}]


def registry():
    return json.loads(get_storage().read_text(workflow.REGISTRY))


def capacity_error():
    return CompanyResearchError("HTTP 429: concurrency_limit",
        status_code=429, code="concurrency_limit", kind=InfrastructureErrorKind.RESOURCE_BUSY,
        provider="companyresearch", operation="research-requests")


@pytest.mark.asyncio
async def test_hold_registers_identity_stops_submissions_and_recovers_fifo(mock_env, monkeypatch):
    adapter = Adapter()
    submit = adapter.submit
    adapter.submit = AsyncMock(side_effect=capacity_error())
    first = await import_companyresearch("older", uid=OTHER, adapter=adapter)
    assert first[0].status == "on_hold" and first[0].error is None
    older = registry()["older"].copy()
    assert older["request_id"] is None

    # Name lookup and LLM disambiguation still run while the research queue is full.
    get_storage().write_text("storage/startups/example/datasets/about.md", "Example AG, Zurich.")
    generate = AsyncMock(return_value={"uid": UID, "rationale": "Matches the dossier."})
    monkeypatch.setattr(identity, "generate_json", generate)
    adapter.submit.reset_mock()
    results = await import_companyresearch("example", company_name="Example AG", adapter=adapter)
    assert adapter.queries == ["Example AG"]
    generate.assert_awaited_once()
    assert {r.startup: r.status for r in results} == {"older": "on_hold", "example": "on_hold"}
    assert all(r.error is None for r in results)
    adapter.submit.assert_awaited_once_with(OTHER, older["idempotency_key"])
    held = registry()
    assert held["example"]["uid"] == UID
    assert held["older"] == older

    # A separate invocation drains in insertion order, keeping the saved keys.
    adapter.submit = submit
    results = await import_companyresearch(adapter=adapter)
    assert adapter.posts == [(OTHER, held["older"]["idempotency_key"]),
                             (UID, held["example"]["idempotency_key"])]
    assert all(r.status == "queued" for r in results)
    adapter.status = "succeeded"
    assert all(r.status == "imported" for r in await import_companyresearch(adapter=adapter))
    assert len(adapter.posts) == 2


@pytest.mark.asyncio
async def test_collects_receipts_after_held_entries_before_any_submission(mock_env):
    adapter = Adapter()
    await import_companyresearch("accepted", uid=UID, adapter=adapter)
    accepted = registry()["accepted"]
    # Older queue entries can precede accepted requests in the existing registry.
    get_storage().write_text(workflow.REGISTRY, json.dumps({
        "held": {"uid": OTHER, "idempotency_key": "held-key", "request_id": None, "status": "on_hold"},
        "accepted": accepted,
    }))
    adapter.status = "succeeded"

    async def reject(uid, key):
        assert workflow._completed(get_storage(), "accepted")
        assert registry()["held"]["status"] == "submitting"
        raise capacity_error()

    adapter.submit = AsyncMock(side_effect=reject)
    results = await import_companyresearch(adapter=adapter)
    assert {r.startup: r.status for r in results} == {"accepted": "imported", "held": "on_hold"}
    adapter.submit.assert_awaited_once_with(OTHER, "held-key")


@pytest.mark.asyncio
async def test_legacy_submitting_enters_hold_without_replacing_key(mock_env):
    adapter = Adapter()
    adapter.fail_post = True
    with pytest.raises(TimeoutError):
        await import_companyresearch("example", uid=UID, adapter=adapter)
    key = registry()["example"]["idempotency_key"]
    submit = adapter.submit
    adapter.submit = AsyncMock(side_effect=capacity_error())
    assert (await import_companyresearch(adapter=adapter))[0].status == "on_hold"
    adapter.submit.assert_awaited_once_with(UID, key)
    adapter.submit = submit
    assert (await import_companyresearch(adapter=adapter))[0].status == "queued"
    assert adapter.posts == [(UID, key), (UID, key)]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code,kind", [
    (401, "invalid_key", InfrastructureErrorKind.AUTHENTICATION),
    (402, "insufficient_credits", InfrastructureErrorKind.RESOURCE_BUSY),
    (429, "rate_limit", InfrastructureErrorKind.RATE_LIMIT),
])
async def test_other_submission_errors_are_not_disguised_as_holds(mock_env, status, code, kind):
    adapter = Adapter()
    adapter.submit = AsyncMock(side_effect=CompanyResearchError(
        "Request rejected", status_code=status, code=code, kind=kind,
        provider="companyresearch", operation="research-requests"))
    with pytest.raises(CompanyResearchError):
        await import_companyresearch("example", uid=UID, adapter=adapter)
    result = (await import_companyresearch(adapter=adapter))[0]
    assert result.status == "error" and result.error
    assert registry()["example"]["status"] == "submitting"


@pytest.mark.asyncio
async def test_explicit_uid_bypasses_discovery_and_pending_does_not_resubmit(mock_env, monkeypatch):
    discovery = AsyncMock(side_effect=AssertionError("must not discover"))
    monkeypatch.setattr(workflow, "resolve_uid", discovery)
    adapter = Adapter()
    first = await import_companyresearch("Example", uid="CHE 123 456 789", adapter=adapter)
    assert first[0].status == "queued"
    assert not get_storage().exists("storage/startups/example/datasets/companyresearch-ch")
    second = await import_companyresearch("Example", adapter=adapter)
    assert second[0].status == "queued"
    assert len(adapter.posts) == 1
    assert len(adapter.gets) == 1
    discovery.assert_not_called()


@pytest.mark.asyncio
async def test_sweep_routes_each_report_and_reuses_completed_without_api(mock_env, monkeypatch):
    adapter = Adapter()
    await import_companyresearch("Example", uid=UID, adapter=adapter)
    await import_companyresearch("Other", uid=OTHER, adapter=adapter)
    adapter.status = "succeeded"
    results = await import_companyresearch(adapter=adapter)
    assert {r.startup for r in results} == {"example", "other"}
    assert all(r.status == "imported" for r in results)
    storage = get_storage()
    for startup, uid in [("example", UID), ("other", OTHER)]:
        root = f"storage/startups/{startup}/datasets/companyresearch-ch"
        assert json.loads(storage.read_text(root + "/report.json"))["companyIdentity"]["uid"] == uid
        md = storage.read_text(root + "/report.md")
        assert uid in md and "source-1" in md and "https://example.org/evidence" in md
    monkeypatch.setattr(workflow, "CompanyResearchAdapter", lambda: pytest.fail("cache needs no API key"))
    previous = Path(results[0].report_path).stat().st_mtime_ns
    reused = await import_companyresearch("example")
    assert reused[0].status == "imported"
    assert Path(results[0].report_path).stat().st_mtime_ns == previous


@pytest.mark.asyncio
async def test_timeout_reuses_persisted_idempotency_key(mock_env):
    adapter = Adapter()
    adapter.fail_post = True
    with pytest.raises(TimeoutError):
        await import_companyresearch("example", uid=UID, adapter=adapter)
    saved = registry()["example"]
    assert saved["status"] == "submitting" and saved["request_id"] is None
    results = await import_companyresearch(adapter=adapter)
    assert adapter.posts[0] == adapter.posts[1]
    assert results[0].status == "queued"


@pytest.mark.asyncio
async def test_failed_download_remains_collectable_without_research(mock_env):
    adapter = Adapter(status="succeeded")
    adapter.fail_download = True
    with pytest.raises(TimeoutError):
        await import_companyresearch("example", uid=UID, adapter=adapter)
    assert registry()["example"]["status"] == "succeeded"
    adapter.fail_download = False
    assert (await import_companyresearch(adapter=adapter))[0].status == "imported"
    assert len(adapter.posts) == 1


@pytest.mark.asyncio
async def test_publication_failure_retry_preserves_other_sources(mock_env, monkeypatch):
    adapter = Adapter(status="succeeded")
    storage = get_storage()
    storage.write_text("storage/startups/example/datasets/legal.md", "Keep me")
    publish = workflow.replace_directory_snapshot
    monkeypatch.setattr(workflow, "replace_directory_snapshot", lambda *a: (_ for _ in ()).throw(OSError("disk error")))
    with pytest.raises(OSError):
        await import_companyresearch("example", uid=UID, adapter=adapter)
    assert not workflow._completed(storage, "example")
    monkeypatch.setattr(workflow, "replace_directory_snapshot", publish)
    assert (await import_companyresearch(adapter=adapter))[0].status == "imported"
    assert storage.read_text("storage/startups/example/datasets/legal.md") == "Keep me"
    assert len(adapter.posts) == 1


@pytest.mark.asyncio
async def test_wrong_report_uid_is_not_published(mock_env):
    adapter = Adapter(status="succeeded")
    adapter.report = AsyncMock(return_value=report(OTHER))
    with pytest.raises(ValueError, match="report UID"):
        await import_companyresearch("example", uid=UID, adapter=adapter)
    assert not workflow._completed(get_storage(), "example")


@pytest.mark.asyncio
async def test_wrong_receipt_uid_does_not_redirect_a_dossier(mock_env):
    adapter = Adapter(status="succeeded")
    adapter.submit = AsyncMock(return_value=adapter.value(OTHER, "wrong-request"))
    with pytest.raises(ValueError, match="receipt UID"):
        await import_companyresearch("example", uid=UID, adapter=adapter)
    assert not adapter.downloads
    assert registry()["example"]["uid"] == UID
    assert registry()["example"]["request_id"] is None


@pytest.mark.asyncio
async def test_corrupt_registry_is_not_replaced(mock_env):
    storage = get_storage()
    storage.write_text(workflow.REGISTRY, '{"../wrong": {}}')
    adapter = Adapter()
    with pytest.raises(ValueError, match="registry"):
        await import_companyresearch("example", uid=UID, adapter=adapter)
    assert storage.read_text(workflow.REGISTRY) == '{"../wrong": {}}'
    assert not adapter.posts


@pytest.mark.asyncio
async def test_terminal_failure_does_not_resubmit(mock_env):
    adapter = Adapter(status="failed")
    first = await import_companyresearch("example", uid=UID, adapter=adapter)
    second = await import_companyresearch("example", uid=UID, adapter=adapter)
    assert first[0].status == second[0].status == "failed"
    assert second[0].error == "research_failed"
    assert len(adapter.posts) == 1


@pytest.mark.asyncio
async def test_one_failed_collection_does_not_block_other_dossier(mock_env):
    adapter = Adapter()
    await import_companyresearch("example", uid=UID, adapter=adapter)
    await import_companyresearch("other", uid=OTHER, adapter=adapter)
    adapter.status = "succeeded"
    original = adapter.report
    async def get_report(uid, run):
        if uid == UID:
            raise TimeoutError("not available")
        return await original(uid, run)
    adapter.report = get_report
    results = await import_companyresearch(adapter=adapter)
    assert {r.startup: r.status for r in results} == {"example": "error", "other": "imported"}


@pytest.mark.asyncio
async def test_concurrent_calls_submit_only_once(mock_env):
    adapter = Adapter()
    await asyncio.gather(*(import_companyresearch("example", uid=UID, adapter=adapter) for _ in range(3)))
    assert len(adapter.posts) == 1


@pytest.mark.asyncio
async def test_empty_sweep_needs_no_credentials(mock_env, monkeypatch):
    monkeypatch.setattr(workflow, "CompanyResearchAdapter", lambda: pytest.fail("no API needed"))
    assert await import_companyresearch() == []
    with pytest.raises(ValueError, match="destination"):
        await import_companyresearch(uid=UID)


@pytest.mark.asyncio
async def test_uid_evidence_is_matched_by_llm_with_candidate_enum(mock_env, monkeypatch):
    storage = get_storage()
    storage.write_text("storage/startups/example/datasets/application.md.txt",
                       "Example AG, Zurich. Official company number CHE-123.456.789. Builds robots.")
    generate = AsyncMock(return_value={"uid": UID, "rationale": "Application identifies Example AG and its UID."})
    monkeypatch.setattr(identity, "generate_json", generate)
    adapter = Adapter()
    result = await import_companyresearch("example", adapter=adapter)
    assert result[0].uid == UID
    assert adapter.queries == [UID]
    assert generate.call_args.args[1]["properties"]["uid"]["enum"] == [UID, None]
    assert "application.md.txt" in generate.call_args.kwargs["cacheable_prompt_prefix"]


@pytest.mark.asyncio
async def test_name_lookup_without_uid_and_unresolved_identity(mock_env, monkeypatch):
    get_storage().write_text("storage/startups/example/datasets/website/index.md", "Example AG is based in Zurich.")
    generate = AsyncMock(return_value={"uid": None, "rationale": "Insufficient identity evidence"})
    monkeypatch.setattr(identity, "generate_json", generate)
    adapter = Adapter()
    with pytest.raises(ValueError, match="unresolved"):
        await import_companyresearch("example", company_name="Example AG", adapter=adapter)
    assert adapter.queries == ["Example AG"]
    assert not adapter.posts


@pytest.mark.asyncio
async def test_no_candidates_errors_without_llm_retry(mock_env, monkeypatch):
    get_storage().write_text("storage/startups/example/datasets/about.md", "Example builds robots in Zurich.")
    monkeypatch.setattr(identity, "generate_json", AsyncMock(side_effect=AssertionError("no LLM")))
    adapter = Adapter()
    adapter.suggestions = AsyncMock(return_value=[])
    with pytest.raises(ValueError, match="no candidate"):
        await import_companyresearch("example", adapter=adapter)
    assert not adapter.posts


def test_cli_and_harness_share_optional_arguments(monkeypatch):
    cli = importlib.import_module("skills.import_companyresearch.__main__")
    fake = AsyncMock(return_value=[])
    monkeypatch.setattr(cli, "import_companyresearch", fake)
    assert CliRunner().invoke(cli.app, ["--help"]).exit_code == 0
    assert CliRunner().invoke(cli.app, []).exit_code == 0
    fake.assert_awaited_with(None, uid=None, company_name=None)
    assert CliRunner().invoke(cli.app, ["example", "--uid", UID]).exit_code == 0
    fake.assert_awaited_with("example", uid=UID, company_name=None)
    package = importlib.import_module("skills.import_companyresearch")
    monkeypatch.setattr(package, "import_companyresearch", fake)
    from skills.harness.harness import dispatch_command
    assert asyncio.run(dispatch_command('/import_companyresearch example --company-name "Example AG"')) == "[]"
    fake.assert_awaited_with("example", uid=None, company_name="Example AG")


def test_cli_hold_is_success_not_failure(monkeypatch):
    cli = importlib.import_module("skills.import_companyresearch.__main__")
    monkeypatch.setattr(cli, "import_companyresearch", AsyncMock(return_value=[
        workflow.CompanyResearchImportResult("example", UID, "on_hold")]))
    result = CliRunner().invoke(cli.app, [])
    assert result.exit_code == 0
    assert json.loads(result.stdout)[0]["status"] == "on_hold"


class Response:
    def __init__(self, status, data, headers=None):
        self.status_code, self.data, self.headers = status, data, headers or {}

    def json(self):
        return self.data


def test_adapter_accepts_uppercase_environment_key(mock_env, monkeypatch):
    from lib.infrastructure.companyresearch import CompanyResearchAdapter
    monkeypatch.delenv("companyresearch_api_key", raising=False)
    monkeypatch.setenv("COMPANYRESEARCH_API_KEY", "uppercase-test-key")
    adapter = CompanyResearchAdapter()
    try:
        assert adapter.key == "uppercase-test-key"
    finally:
        adapter.close()


class Session:
    def __init__(self, responses):
        self.responses, self.calls = iter(responses), []

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return next(self.responses)


@pytest.mark.asyncio
async def test_adapter_validates_and_sanitizes_failures(mock_env, monkeypatch):
    from lib.infrastructure.companyresearch import CompanyResearchAdapter
    monkeypatch.setenv("companyresearch_api_key", "secret-test-key")
    session = Session([Response(200, {"items": [{"uid": UID}]}),
                       Response(402, {"code": "insufficient_credits", "detail": "secret-test-key"})])
    adapter = CompanyResearchAdapter(session=session)
    with pytest.raises(InfrastructureError, match="Invalid API response"):
        await adapter.suggestions("example")
    with pytest.raises(InfrastructureError, match="insufficient_credits") as error:
        await adapter.submit(UID, "operation-1")
    assert "secret-test-key" not in str(error.value)
    assert not error.value.recoverable
    assert session.calls[1][1]["headers"]["Idempotency-Key"] == "operation-1"
    assert session.calls[1][1]["json"] == {"uid": UID, "refresh": False}
    assert session.calls[1][1]["allow_redirects"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 503])
async def test_adapter_retry_keeps_post_key(mock_env, monkeypatch, status):
    module = importlib.import_module("lib.infrastructure.companyresearch")
    monkeypatch.setenv("companyresearch_api_key", "secret-test-key")
    original = module.with_rate_limit_retry
    async def fast_retry(operation, **kwargs):
        return await original(operation, delays=(0,), **kwargs)
    monkeypatch.setattr(module, "with_rate_limit_retry", fast_retry)
    receipt = {"requestId": "a" * 64, "status": "queued", "companyUid": UID,
               "runId": None, "reportUrl": None, "billing": {"disposition": "reserved", "credits": 50},
               "createdAt": "2026-10-20T12:00:00Z", "error": None}
    session = Session([Response(status, {"code": "rate_limit"}, {"Retry-After": "0"}), Response(202, receipt)])
    assert (await module.CompanyResearchAdapter(session=session).submit(UID, "key-1"))["status"] == "queued"
    assert all(call[1]["headers"]["Idempotency-Key"] == "key-1" for call in session.calls)


@pytest.mark.asyncio
async def test_adapter_capacity_is_structured_without_sleep_or_retry(mock_env, monkeypatch):
    module = importlib.import_module("lib.infrastructure.companyresearch")
    monkeypatch.setenv("companyresearch_api_key", "secret-test-key")
    sleep = AsyncMock(side_effect=AssertionError("capacity must not wait"))
    monkeypatch.setattr(asyncio, "sleep", sleep)
    session = Session([Response(429, {"code": "concurrency_limit", "detail": "secret-test-key"},
                                {"Retry-After": "300"})])
    with pytest.raises(CompanyResearchError) as error:
        await module.CompanyResearchAdapter(session=session).submit(UID, "key-1")
    assert error.value.concurrency_limited
    assert error.value.kind == InfrastructureErrorKind.RESOURCE_BUSY
    assert error.value.recoverable
    assert "secret-test-key" not in str(error.value)
    assert len(session.calls) == 1
    sleep.assert_not_awaited()
