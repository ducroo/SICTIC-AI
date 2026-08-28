import asyncio
import json

import pytest

from lib.datasets.manifest import IngestionManifest
from lib.datasets.paths import dataset_location_for_domain
from lib.storage import get_storage
from skills.batch_audit.structured import batch_audit_json


CHECKLIST = """# Legal Due Diligence

## Legal

### Chamber registration

Is the company registered in the commercial registry?

**Keywords:** chamber of commerce, registration number

### Legal form

Is the current legal form established?
"""


def _indexed_dataset(name: str = "example-startup") -> None:
    location = dataset_location_for_domain(name, "startups")
    storage = get_storage()
    storage.mkdir(location.raw_rel)
    manifest = IngestionManifest(storage, location.parsed_rel)
    manifest.indexed_dataset_revision = "revision-1"
    manifest.save()


@pytest.mark.asyncio
async def test_structured_batch_audit_saves_json_insight(
    mock_env,
    monkeypatch,
):
    _indexed_dataset()
    calls = []

    async def fake_dataset_chat(**kwargs):
        calls.append(kwargs)
        return json.dumps(
            {
                "status": "Fine",
                "rationale": "Evidence found.",
                "source_documents": ["Registry.pdf — page 1"],
                "proposed_next_steps_and_questions": [],
            }
        )

    monkeypatch.setattr(
        "skills.batch_audit.structured.dataset_chat",
        fake_dataset_chat,
    )
    monkeypatch.setattr(
        "skills.batch_audit.structured.llm_model",
        lambda: "google/gemini-2.5-pro",
    )

    insight = await batch_audit_json(
        dataset_name="example-startup",
        skill_name="dd_checks",
        checklist_markdown=CHECKLIST,
        llm_instructions="Use only supplied evidence and return JSON.",
        status_scale=[
            "Not Found",
            "Critical",
            "Borderline",
            "Sufficient",
            "Fine",
        ],
        missing_evidence_status="Not Found",
    )

    assert insight.filename == (
        "dd-checks-legal-due-diligence-gemini-2-5-pro.json"
    )
    assert insight.directory.endswith("/insights/batch-audit")
    audit = json.loads(insight.content())
    assert audit["checklist_title"] == "Legal Due Diligence"
    assert audit["chapters"][0]["checks"][0]["status"] == "Fine"
    assert len(calls) == 2
    assert calls[0]["queries"] == [
        "Is the company registered in the commercial registry?",
        "Is the company registered in the commercial registry?\n\n"
        "Relevant terminology: chamber of commerce, registration number",
    ]
    assert "chamber of commerce" not in calls[0]["prompt"]
    response_schema = calls[0]["response_format"]["json_schema"]["schema"]
    assert calls[0]["response_format"]["json_schema"]["strict"] is True
    assert response_schema["properties"]["status"]["enum"] == [
        "Not Found",
        "Critical",
        "Borderline",
        "Sufficient",
        "Fine",
    ]
    prefix = calls[0]["cacheable_prompt_prefix"]
    assert '"status"' in prefix
    assert prefix.index("### AUDIT INSTRUCTIONS — START") < (
        prefix.index('"status"')
    )
    assert "### CURRENT CHECK — START" not in prefix
    assert calls[0]["prompt"].index("### CURRENT CHECK — START") < (
        calls[0]["prompt"].index(
            "Is the company registered in the commercial registry?"
        )
    )


@pytest.mark.asyncio
async def test_structured_batch_audit_warms_one_check_before_concurrent_fanout(
    mock_env,
    monkeypatch,
):
    from skills.batch_audit import structured

    _indexed_dataset()
    checklist = CHECKLIST + """

### Registered office

Is the registered office documented?
"""
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    remaining_started = asyncio.Event()
    release_remaining = asyncio.Event()
    started = []

    async def fake_run_check(
        _dataset_name,
        check,
        _llm_instructions,
        _response_schema,
        _status_scale,
        _missing_evidence_status,
    ):
        started.append(check.number)
        if check.number == "1.1":
            first_started.set()
            await release_first.wait()
        else:
            if len(started) == 3:
                remaining_started.set()
            await release_remaining.wait()
        return {
            "status": "Pass",
            "rationale": f"Completed {check.number}.",
            "source_documents": [],
            "proposed_next_steps_and_questions": [],
            "error": None,
        }

    monkeypatch.setattr(structured, "_run_check", fake_run_check)
    audit_task = asyncio.create_task(
        batch_audit_json(
            dataset_name="example-startup",
            skill_name="submission_ready",
            checklist_markdown=checklist,
            llm_instructions="Return JSON.",
            status_scale=["Pass", "Fail", "Unclear"],
            missing_evidence_status="Unclear",
        )
    )

    await first_started.wait()
    assert started == ["1.1"]

    release_first.set()
    await remaining_started.wait()
    assert started == ["1.1", "1.2", "1.3"]

    release_remaining.set()
    insight = await audit_task
    checks = json.loads(insight.content())["chapters"][0]["checks"]
    assert [check["number"] for check in checks] == ["1.1", "1.2", "1.3"]


@pytest.mark.asyncio
async def test_structured_batch_audit_retries_invalid_responses(
    mock_env,
    monkeypatch,
):
    _indexed_dataset()
    calls = []

    async def fake_dataset_chat(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return ""
        if len(calls) == 2:
            return '{"status":"Maybe"}'
        return json.dumps(
            {
                "status": "Pass",
                "rationale": "Evidence found.",
                "source_documents": [],
                "proposed_next_steps_and_questions": [],
            }
        )

    monkeypatch.setattr(
        "skills.batch_audit.structured.dataset_chat",
        fake_dataset_chat,
    )

    insight = await batch_audit_json(
        dataset_name="example-startup",
        skill_name="submission_ready",
        checklist_markdown=CHECKLIST.replace(
            "### Legal form\n\nIs the current legal form established?\n",
            "",
        ),
        llm_instructions="Return JSON.",
        status_scale=["Pass", "Fail", "Unclear"],
        missing_evidence_status="Unclear",
    )

    check = json.loads(insight.content())["chapters"][0]["checks"][0]
    assert len(calls) == 3
    assert check["status"] == "Pass"
    assert check["error"] is None
    assert "Audit model returned no content" in calls[1]["prompt"]
    assert "does not match the schema" in calls[2]["prompt"]
    assert "Audit model returned no content" not in calls[2]["prompt"]


@pytest.mark.asyncio
async def test_structured_batch_audit_preserves_missing_evidence_fallback(
    mock_env,
    monkeypatch,
):
    from skills.dataset_chat.dataset_chat import _fallback_trigger

    _indexed_dataset()
    calls = 0

    async def fake_dataset_chat(**_kwargs):
        nonlocal calls
        calls += 1
        return _fallback_trigger()

    monkeypatch.setattr(
        "skills.batch_audit.structured.dataset_chat",
        fake_dataset_chat,
    )

    insight = await batch_audit_json(
        dataset_name="example-startup",
        skill_name="submission_ready",
        checklist_markdown=CHECKLIST.replace(
            "### Legal form\n\nIs the current legal form established?\n",
            "",
        ),
        llm_instructions="Return JSON.",
        status_scale=["Pass", "Fail", "Unclear"],
        missing_evidence_status="Unclear",
    )

    check = json.loads(insight.content())["chapters"][0]["checks"][0]
    assert calls == 1
    assert check["status"] == "Unclear"
    assert check["error"] is None


@pytest.mark.asyncio
async def test_structured_batch_audit_records_exhausted_schema_errors(
    mock_env,
    monkeypatch,
):
    _indexed_dataset()
    calls = {"count": 0}

    async def failing_dataset_chat(**_kwargs):
        calls["count"] += 1
        raise ValueError("LLM response does not match the schema at $.status")

    monkeypatch.setattr(
        "skills.batch_audit.structured.dataset_chat",
        failing_dataset_chat,
    )

    insight = await batch_audit_json(
        dataset_name="example-startup",
        skill_name="submission_ready",
        checklist_markdown=CHECKLIST,
        llm_instructions="Return JSON.",
        status_scale=["Pass", "Fail", "Unclear"],
        missing_evidence_status="Unclear",
    )

    checks = json.loads(insight.content())["chapters"][0]["checks"]
    assert calls["count"] == 6
    assert all(check["status"] is None for check in checks)
    assert all("failed after 3 attempts" in check["error"] for check in checks)

    async def recovered_dataset_chat(**_kwargs):
        return json.dumps(
            {
                "status": "Pass",
                "rationale": "Provider recovered.",
                "source_documents": [],
                "proposed_next_steps_and_questions": [],
            }
        )

    monkeypatch.setenv("RANKED_LLMS", "ollama/test-model:1b")
    monkeypatch.setattr(
        "skills.batch_audit.structured.dataset_chat",
        recovered_dataset_chat,
    )
    recovered = await batch_audit_json(
        dataset_name="example-startup",
        skill_name="submission_ready",
        checklist_markdown=CHECKLIST,
        llm_instructions="Return JSON.",
        status_scale=["Pass", "Fail", "Unclear"],
        missing_evidence_status="Unclear",
    )

    recovered_checks = json.loads(recovered.content())["chapters"][0]["checks"]
    assert all(check["status"] == "Pass" for check in recovered_checks)
    assert all(check["error"] is None for check in recovered_checks)


@pytest.mark.asyncio
async def test_structured_batch_audit_does_not_retry_timeouts(
    mock_env,
    monkeypatch,
):
    _indexed_dataset()
    calls = {"count": 0}

    async def timing_out_dataset_chat(**_kwargs):
        calls["count"] += 1
        raise TimeoutError("LLM request timed out after 180s")

    monkeypatch.setattr(
        "skills.batch_audit.structured.dataset_chat",
        timing_out_dataset_chat,
    )

    insight = await batch_audit_json(
        dataset_name="example-startup",
        skill_name="submission_ready",
        checklist_markdown=CHECKLIST,
        llm_instructions="Return JSON.",
        status_scale=["Pass", "Fail", "Unclear"],
        missing_evidence_status="Unclear",
    )

    checks = json.loads(insight.content())["chapters"][0]["checks"]
    assert calls["count"] == 2
    assert all("timed out" in check["error"] for check in checks)
    assert all("failed after 3 attempts" not in check["error"] for check in checks)


@pytest.mark.asyncio
async def test_structured_batch_audit_reuses_fresh_json(
    mock_env,
    monkeypatch,
):
    _indexed_dataset()
    monkeypatch.setenv("RANKED_LLMS", "ollama/test-model:1b")
    response = json.dumps(
        {
            "status": "Pass",
            "rationale": "Evidence found.",
            "source_documents": [],
            "proposed_next_steps_and_questions": [],
        }
    )

    async def fake_dataset_chat(**_kwargs):
        return response

    monkeypatch.setattr(
        "skills.batch_audit.structured.dataset_chat",
        fake_dataset_chat,
    )
    kwargs = {
        "dataset_name": "example-startup",
        "skill_name": "submission_ready",
        "checklist_markdown": CHECKLIST,
        "llm_instructions": "Return JSON.",
        "status_scale": ["Pass", "Fail", "Unclear"],
        "missing_evidence_status": "Unclear",
    }
    generated = await batch_audit_json(**kwargs)

    async def forbidden_dataset_chat(**_kwargs):
        raise AssertionError("A fresh audit must be reused.")

    monkeypatch.setattr(
        "skills.batch_audit.structured.dataset_chat",
        forbidden_dataset_chat,
    )
    reused = await batch_audit_json(**kwargs)

    assert reused.path == generated.path
