import pytest

from lib.startups.dealum import DealumMatch
from skills.submission_ready.submission_ready import (
    SubmissionReadyResult,
    _canonical_stage,
    _parse_proposed_action,
    _process_candidate,
    _render_proposed_action,
    _resolve_candidates,
    run_submission_query,
    submission_ready,
)


@pytest.mark.asyncio
async def test_submission_query_returns_strict_schema(monkeypatch):
    async def fake_dataset_chat(*args, **kwargs):
        return (
            '{"judgment":"Pass","assessment":"Founder submitted it.",'
            '"source_documents":["Dealum Application — Contact"],'
            '"proposed_next_step":"No action"}'
        )

    monkeypatch.setattr(
        "skills.submission_ready.submission_ready.dataset_chat",
        fake_dataset_chat,
    )

    result = await run_submission_query(
        "example",
        "Was it submitted by a founder?",
        "1.1",
        "Return JSON.",
    )

    assert result == {
        "judgment": "Pass",
        "assessment": "Founder submitted it.",
        "source_documents": "Dealum Application — Contact",
        "proposed_next_step": "No action",
    }


@pytest.mark.asyncio
async def test_submission_query_keeps_missing_evidence_unclear(monkeypatch):
    async def fake_dataset_chat(*args, **kwargs):
        return "INSUFFICIENT_CONTEXT"

    monkeypatch.setattr(
        "skills.submission_ready.submission_ready.dataset_chat",
        fake_dataset_chat,
    )
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready._fallback_trigger",
        lambda: "INSUFFICIENT_CONTEXT",
    )

    result = await run_submission_query(
        "example",
        "What is the valuation?",
        "5.1",
        "Return JSON.",
    )

    assert result["judgment"] == "Unclear"
    assert "does not establish" in result["assessment"]
    assert result["source_documents"] == "None"


@pytest.mark.asyncio
async def test_submission_query_retries_invalid_judgment_three_times(
    monkeypatch,
):
    calls = 0

    async def fake_dataset_chat(*args, **kwargs):
        nonlocal calls
        calls += 1
        return (
            '{"judgment":"Probably","assessment":"Maybe",'
            '"source_documents":[],"proposed_next_step":"Review"}'
        )

    monkeypatch.setattr(
        "skills.submission_ready.submission_ready.dataset_chat",
        fake_dataset_chat,
    )

    with pytest.raises(RuntimeError, match="failed after 3 attempts"):
        await run_submission_query(
            "example",
            "What is the valuation?",
            "5.1",
            "Return JSON.",
        )

    assert calls == 3


def _application(name, step, application_id):
    return {
        "id": application_id,
        "name": name,
        "code": f"CODE-{application_id}",
        "step": step,
    }


class FakeAdapter:
    dealroom_id = "test-room"

    def __init__(self, applications):
        self.applications = applications
        self.list_calls = 0

    def is_configured(self):
        return True

    def list_applications(self):
        self.list_calls += 1
        return self.applications


def _match(name="Example", step="Application", application_id=1):
    application = _application(name, step, application_id)
    return DealumMatch(
        requested_startup=name,
        matched_name=name,
        dataset_slug=name.casefold(),
        dealum_id=application_id,
        dealum_url="https://example.test",
        application_code=application["code"],
        application_date=None,
        step=step,
        match_method="normalized_name",
        selection_method="single_match",
        application=application,
    )


def test_submission_ready_stage_matching_is_case_insensitive():
    assert _canonical_stage(" APPLICATION ") == "Application"
    assert _canonical_stage("under_review") == "Under review"
    assert _canonical_stage("Jury") is None


def test_resolve_candidates_excludes_jury_and_later_stages():
    applications = [
        _application("Alpha", "Application", 1),
        _application("Beta", "UNDER REVIEW", 2),
        _application("Gamma", "Jury", 3),
    ]
    adapter = FakeAdapter(applications)

    candidates, statuses = _resolve_candidates(
        applications,
        adapter,
        None,
    )

    assert [(match.matched_name, stage) for match, stage in candidates] == [
        ("Alpha", "Application"),
        ("Beta", "Under review"),
    ]
    assert statuses == []


def test_resolve_explicit_out_of_scope_startup_returns_status():
    applications = [_application("Gamma", "Jury", 3)]

    candidates, statuses = _resolve_candidates(
        applications,
        FakeAdapter(applications),
        ["Gamma"],
    )

    assert candidates == []
    assert statuses[0].status == (
        "outside submission-ready stages; no action"
    )


def test_parse_proposed_action_enforces_eight_concern_limit():
    concerns = [f"Concern {index}" for index in range(9)]
    payload = {
        "proposed_action": "Send concerns to startup",
        "rationale": "Information is missing.",
        "eligibility_concerns": concerns,
        "missing_or_inconsistent_information": [],
    }

    with pytest.raises(ValueError, match="more than 8 concerns"):
        _parse_proposed_action(str(payload).replace("'", '"'), "Application")


def test_proposed_action_markdown_uses_fixed_structure_and_none_identified():
    report = _render_proposed_action(
        "Under review",
        {
            "proposed_action": "Move to Jury",
            "rationale": "The submission is complete.",
            "eligibility_concerns": [],
            "missing_or_inconsistent_information": [],
        },
    )

    assert "- Current stage: Under review" in report
    assert "- Proposed action: Move to Jury" in report
    assert "## Eligibility concerns\n\n- None identified." in report
    assert (
        "## Missing or inconsistent information\n\n- None identified."
        in report
    )


@pytest.mark.asyncio
async def test_batch_invocation_uses_six_hour_processing_mode(
    monkeypatch,
):
    applications = [
        _application("Alpha", "Application", 1),
        _application("Beta", "Under review", 2),
    ]
    adapter = FakeAdapter(applications)
    force_modes = []

    async def fake_process(match, stage, **kwargs):
        force_modes.append(kwargs["force_refresh"])
        return SubmissionReadyResult(
            startup=match.matched_name,
            stage=stage,
            status="unchanged",
        )

    monkeypatch.setattr(
        "skills.submission_ready.submission_ready.DealumAdapter",
        lambda: adapter,
    )
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready.config_load",
        lambda: {"submission_ready": {}},
    )
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready._process_candidate",
        fake_process,
    )

    result = await submission_ready()

    assert len(result) == 2
    assert force_modes == [False, False]
    assert adapter.list_calls == 1


@pytest.mark.asyncio
async def test_explicit_invocation_forces_fresh_import(monkeypatch):
    applications = [_application("Alpha", "Application", 1)]
    adapter = FakeAdapter(applications)
    force_modes = []

    async def fake_process(match, stage, **kwargs):
        force_modes.append(kwargs["force_refresh"])
        return SubmissionReadyResult(
            startup=match.matched_name,
            stage=stage,
            status="unchanged",
        )

    monkeypatch.setattr(
        "skills.submission_ready.submission_ready.DealumAdapter",
        lambda: adapter,
    )
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready.config_load",
        lambda: {"submission_ready": {}},
    )
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready._process_candidate",
        fake_process,
    )

    await submission_ready("Alpha")

    assert force_modes == [True]
    assert adapter.list_calls == 1


@pytest.mark.asyncio
async def test_process_candidate_writes_timestamped_pair(
    mock_env,
    monkeypatch,
):
    from lib.storage import get_storage

    storage = get_storage()
    storage.mkdir("storage/startups/example/datasets")

    async def fake_prepare(*args, **kwargs):
        return "example"

    async def fake_checklist(*args, **kwargs):
        return "| No | Result |\n|---|---|\n| 1 | Pass |"

    async def fake_response(**kwargs):
        return "# Proposed action\n", "response prompt"

    monkeypatch.setattr(
        "skills.submission_ready.submission_ready._prepare_dataset",
        fake_prepare,
    )
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready."
        "_reusable_run_insight",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready._run_checklist",
        fake_checklist,
    )
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready."
        "_generate_proposed_action",
        fake_response,
    )
    config = {
        "policy": "policy",
        "checklist": "# 1 Test\n- Test",
        "llm_instructions": "instructions",
        "table_lines": "table",
        "response_instructions": "response",
        "response_schema": "schema",
    }

    result = await _process_candidate(
        _match(),
        "Application",
        applications=[],
        adapter=FakeAdapter([]),
        force_refresh=True,
        run_id="20260730T221500Z",
        check_config=config,
    )

    expected_root = (
        "storage/startups/example/insights/submission-ready/"
        "20260730T221500Z"
    )
    assert result.checklist_path == (
        f"{expected_root}/checklist-test-model-1b.md"
    )
    assert result.response_path == (
        f"{expected_root}/response-test-model-1b.md"
    )
    assert storage.exists(result.checklist_path)
    assert storage.exists(result.response_path)


@pytest.mark.asyncio
async def test_stage_change_reuses_checklist_without_checklist_llm(
    mock_env,
    monkeypatch,
):
    from lib.storage import get_storage

    storage = get_storage()
    storage.mkdir("storage/startups/example/datasets")

    class ReusableChecklist:
        path = "old/checklist.md"

        def content(self):
            return "# Existing checklist"

    reusable = iter([ReusableChecklist(), None])

    async def fake_prepare(*args, **kwargs):
        return "example"

    async def forbidden_checklist(*args, **kwargs):
        raise AssertionError("Checklist LLM must not run.")

    async def fake_response(**kwargs):
        assert kwargs["stage"] == "Under review"
        assert kwargs["checklist_report"] == "# Existing checklist"
        return "# Proposed action\n", "new response prompt"

    monkeypatch.setattr(
        "skills.submission_ready.submission_ready._prepare_dataset",
        fake_prepare,
    )
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready."
        "_reusable_run_insight",
        lambda *args, **kwargs: next(reusable),
    )
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready._run_checklist",
        forbidden_checklist,
    )
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready."
        "_generate_proposed_action",
        fake_response,
    )
    config = {
        "policy": "policy",
        "checklist": "checklist",
        "llm_instructions": "instructions",
        "table_lines": "table",
        "response_instructions": "response",
        "response_schema": "schema",
    }

    result = await _process_candidate(
        _match(step="Under review"),
        "Under review",
        applications=[],
        adapter=FakeAdapter([]),
        force_refresh=False,
        run_id="20260730T221501Z",
        check_config=config,
    )

    assert result.status.startswith("stage changed")
    assert storage.read_text(result.checklist_path) == "# Existing checklist"


@pytest.mark.asyncio
async def test_unchanged_stage_reuses_both_artifacts_without_llm(
    mock_env,
    monkeypatch,
):
    from lib.storage import get_storage

    get_storage().mkdir("storage/startups/example/datasets")

    class Reusable:
        def __init__(self, path, content):
            self.path = path
            self._content = content

        def content(self):
            return self._content

    reusable = iter(
        [
            Reusable("old/checklist.md", "# Existing checklist"),
            Reusable("old/response.md", "# Existing response"),
        ]
    )

    async def fake_prepare(*args, **kwargs):
        return "example"

    async def forbidden_response(**kwargs):
        raise AssertionError("Response LLM must not run.")

    monkeypatch.setattr(
        "skills.submission_ready.submission_ready._prepare_dataset",
        fake_prepare,
    )
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready."
        "_reusable_run_insight",
        lambda *args, **kwargs: next(reusable),
    )
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready."
        "_generate_proposed_action",
        forbidden_response,
    )
    config = {
        "policy": "policy",
        "checklist": "checklist",
        "llm_instructions": "instructions",
        "table_lines": "table",
        "response_instructions": "response",
        "response_schema": "schema",
    }

    result = await _process_candidate(
        _match(),
        "Application",
        applications=[],
        adapter=FakeAdapter([]),
        force_refresh=False,
        run_id="20260730T221502Z",
        check_config=config,
    )

    assert result.status == "unchanged; reused existing analysis"
    assert result.checklist_path == "old/checklist.md"
    assert result.response_path == "old/response.md"
    assert not get_storage().exists(
        "storage/startups/example/insights/submission-ready/"
        "20260730T221502Z"
    )


@pytest.mark.asyncio
async def test_discovery_failure_retries_and_writes_failure_report(
    monkeypatch,
):
    class FailingAdapter:
        dealroom_id = "test"

        def __init__(self):
            self.calls = 0

        def is_configured(self):
            return True

        def list_applications(self):
            self.calls += 1
            raise RuntimeError("Dealum unavailable")

    adapter = FailingAdapter()
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready.DealumAdapter",
        lambda: adapter,
    )
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready._save_failure_report",
        lambda failures, run_id: "failures.md",
    )

    result = await submission_ready()

    assert adapter.calls == 3
    assert "Failure report: failures.md" in result[0]
