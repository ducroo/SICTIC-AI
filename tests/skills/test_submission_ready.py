import json

import pytest

from lib.insights import InsightFile
from lib.startups.dealum import DealumMatch
from lib.storage import get_storage
from skills.submission_ready.submission_ready import (
    SubmissionReadyResult,
    _canonical_stage,
    _generate_proposed_action,
    _parse_proposed_action,
    _process_candidate,
    _render_proposed_action,
    _resolve_candidates,
    submission_ready,
)


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


def _audit_document(*, error: str | None = None):
    return {
        "schema_version": 1,
        "skill": "submission_ready",
        "checklist_title": "Submission Readiness",
        "dataset": "example",
        "model": "ollama/test_model:1b",
        "generated_at": "2026-08-06T10:00:00Z",
        "status_scale": ["Pass", "Fail", "Unclear"],
        "chapters": [
            {
                "number": "1",
                "title": "Eligibility",
                "checks": [
                    {
                        "number": "1.1",
                        "check": "Founder submission",
                        "status": None if error else "Pass",
                        "rationale": None if error else "Founder evidence.",
                        "source_documents": (
                            [] if error else ["Dealum Application — Contact"]
                        ),
                        "proposed_next_steps_and_questions": [],
                        "error": error,
                    }
                ],
            }
        ],
    }


class FakeAuditInsight:
    path = (
        "storage/startups/example/insights/batch-audit/"
        "submission-ready-submission-readiness-test-model-1b.json"
    )

    def __init__(self, *, error: str | None = None):
        self._content = json.dumps(_audit_document(error=error))

    def content(self):
        return self._content


def _check_config():
    return {
        "policy": "policy",
        "checklist": (
            "# Submission Readiness\n\n## Eligibility\n\n"
            "### Founder submission\n\nWas it submitted by a founder?"
        ),
        "llm_instructions": "instructions",
        "response_instructions": "response",
        "response_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "proposed_action": {"type": "string"},
                "rationale": {"type": "string", "minLength": 1},
                "eligibility_concerns": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "missing_or_inconsistent_information": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": [
                "proposed_action",
                "rationale",
                "eligibility_concerns",
                "missing_or_inconsistent_information",
            ],
        },
    }


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
        _parse_proposed_action(payload, "Application")


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
async def test_proposed_action_uses_stage_specialized_schema(monkeypatch):
    calls = []

    async def fake_generate_json(prompt, schema, reviewer):
        calls.append(
            {
                "prompt": prompt,
                "schema": schema,
                "reviewer": reviewer,
            }
        )
        return {
            "proposed_action": "Move to Jury",
            "rationale": "The submission is complete.",
            "eligibility_concerns": [],
            "missing_or_inconsistent_information": [],
        }

    monkeypatch.setattr(
        "skills.submission_ready.submission_ready.generate_json",
        fake_generate_json,
    )

    report, _prompt = await _generate_proposed_action(
        stage="Under review",
        checklist_report="All checks pass.",
        response_instructions="Recommend an action.",
        response_schema=_check_config()["response_schema"],
    )

    schema = calls[-1]["schema"]
    assert schema["properties"]["proposed_action"]["enum"] == [
        "Move to Jury",
        "Send concerns to startup",
    ]
    assert len(calls) == 1
    assert calls[0]["reviewer"]({"proposed_action": "Move to Jury"}).problems
    assert "Move to Jury" in report


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
        "skills.submission_ready.submission_ready.load_repository_config",
        lambda *sections: {},
    )
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready._process_candidate",
        fake_process,
    )

    result = await submission_ready()

    assert result == []
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
        "skills.submission_ready.submission_ready.load_repository_config",
        lambda *sections: {},
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

    batch_calls = []

    async def fake_batch_audit(**kwargs):
        batch_calls.append(kwargs)
        return FakeAuditInsight()

    async def fake_response(**kwargs):
        return "# Proposed action\n", "response prompt"

    monkeypatch.setattr(
        "skills.submission_ready.submission_ready._prepare_dataset",
        fake_prepare,
    )
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready._reusable_run_insight",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready.batch_audit",
        fake_batch_audit,
    )
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready."
        "_generate_proposed_action",
        fake_response,
    )
    result = await _process_candidate(
        _match(),
        "Application",
        applications=[],
        adapter=FakeAdapter([]),
        force_refresh=True,
        run_id="20260730T221500Z",
        check_config=_check_config(),
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
    assert batch_calls[0]["skill_name"] == "submission_ready"
    assert batch_calls[0]["status_scale"] == ["Pass", "Fail", "Unclear"]
    checklist_report = storage.read_text(result.checklist_path)
    assert "| No | Check | Status | Rationale | Source documents |" in checklist_report
    assert "| 1.1 | Founder submission | Pass | Founder evidence." in checklist_report


@pytest.mark.asyncio
async def test_stage_change_uses_current_batch_audit_for_new_response(
    mock_env,
    monkeypatch,
):
    from lib.storage import get_storage

    storage = get_storage()
    storage.mkdir("storage/startups/example/datasets")

    async def fake_prepare(*args, **kwargs):
        return "example"

    async def fake_batch_audit(**_kwargs):
        return FakeAuditInsight()

    async def fake_response(**kwargs):
        assert kwargs["stage"] == "Under review"
        assert "| 1.1 | Founder submission | Pass |" in kwargs["checklist_report"]
        return "# Proposed action\n", "new response prompt"

    monkeypatch.setattr(
        "skills.submission_ready.submission_ready._prepare_dataset",
        fake_prepare,
    )
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready._reusable_run_insight",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready.batch_audit",
        fake_batch_audit,
    )
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready."
        "_generate_proposed_action",
        fake_response,
    )
    result = await _process_candidate(
        _match(step="Under review"),
        "Under review",
        applications=[],
        adapter=FakeAdapter([]),
        force_refresh=False,
        run_id="20260730T221501Z",
        check_config=_check_config(),
    )

    assert result.status == "generated checklist and proposed action"
    assert "Completeness and Eligibility" in storage.read_text(result.checklist_path)


@pytest.mark.asyncio
async def test_unchanged_stage_reuses_both_artifacts_without_llm(
    mock_env,
    monkeypatch,
):
    from lib.storage import get_storage

    get_storage().mkdir("storage/startups/example/datasets")

    old_run = "20260730T210000Z"
    old_root = f"storage/startups/example/insights/submission-ready/{old_run}"
    get_storage().mkdir(old_root)
    old_checklist = f"{old_root}/checklist-test-model-1b.md"
    old_response = f"{old_root}/response-test-model-1b.md"
    get_storage().write_text(old_checklist, "# Existing checklist")
    get_storage().write_text(old_response, "# Existing response")

    class ReusableResponse:
        path = old_response
        run_id = old_run

    async def fake_prepare(*args, **kwargs):
        return "example"

    async def fake_batch_audit(**_kwargs):
        return FakeAuditInsight()

    async def forbidden_response(**kwargs):
        raise AssertionError("Response LLM must not run.")

    monkeypatch.setattr(
        "skills.submission_ready.submission_ready._prepare_dataset",
        fake_prepare,
    )
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready."
        "_reusable_run_insight",
        lambda *args, **kwargs: ReusableResponse(),
    )
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready.batch_audit",
        fake_batch_audit,
    )
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready."
        "_generate_proposed_action",
        forbidden_response,
    )
    result = await _process_candidate(
        _match(),
        "Application",
        applications=[],
        adapter=FakeAdapter([]),
        force_refresh=False,
        run_id="20260730T221502Z",
        check_config=_check_config(),
    )

    assert result.status == "unchanged; reused existing analysis"
    assert result.checklist_path == old_checklist
    assert result.response_path == old_response
    assert not get_storage().exists(
        "storage/startups/example/insights/submission-ready/"
        "20260730T221502Z"
    )


@pytest.mark.asyncio
async def test_process_candidate_rejects_batch_audit_technical_errors(
    mock_env,
    monkeypatch,
):
    get_storage().mkdir("storage/startups/example/datasets")

    async def fake_prepare(*args, **kwargs):
        return "example"

    async def failed_batch_audit(**_kwargs):
        return FakeAuditInsight(error="provider unavailable")

    monkeypatch.setattr(
        "skills.submission_ready.submission_ready._prepare_dataset",
        fake_prepare,
    )
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready.batch_audit",
        failed_batch_audit,
    )

    with pytest.raises(RuntimeError, match="1 technical failure"):
        await _process_candidate(
            _match(),
            "Application",
            applications=[],
            adapter=FakeAdapter([]),
            force_refresh=False,
            run_id="20260730T221503Z",
            check_config=_check_config(),
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
    failure_insight = InsightFile(
        "submission-ready-runs",
        "submission_ready",
        "manual",
        identifier="failures",
        subdir=True,
    )
    saved_failures = []
    monkeypatch.setattr(
        "skills.submission_ready.submission_ready._save_failure_report",
        lambda failures, run_id: saved_failures.extend(failures) or failure_insight,
    )

    with pytest.raises(
        RuntimeError,
        match="Submission-ready discovery failed",
    ):
        await submission_ready()

    assert adapter.calls == 3
    assert len(saved_failures) == 1
