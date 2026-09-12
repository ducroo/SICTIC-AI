import asyncio
import importlib
from pathlib import Path
import json

import pytest

from lib.batch_audit import batch_audit
from lib.datasets.manifest import IngestionManifest
from lib.datasets.paths import dataset_location_for_domain
from lib.storage import get_storage

AUDIT_SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "config/submission_ready/audit_response_schema.json").read_text()
)


DD_SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "config/dd_checks/audit_response_schema.json").read_text()
)

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
@pytest.mark.parametrize("shared_evidence", [False, True])
async def test_batch_audit_assesses_available_context_when_search_has_no_hits(
    mock_env, monkeypatch, shared_evidence,
):
    """Zero hits must not bypass assessment of supplied documentary evidence."""
    _indexed_dataset()
    chat = importlib.import_module("skills.dataset_chat.dataset_chat")
    searches = []
    generations = []

    async def no_hits(dataset_name, queries, **kwargs):
        assert kwargs["raise_on_error"] is True
        searches.append(queries)
        return []

    async def assess(prompt, schema, reviewer, *, cacheable_prompt_prefix):
        generations.append(prompt)
        assert "CURRENT CHECK" in prompt
        if shared_evidence:
            assert "Registry.pdf — page 1" in cacheable_prompt_prefix
        result = {
            "status": "Fine" if shared_evidence else "Not Found",
            "rationale": (
                "The supplied registry extract establishes registration and legal form."
                if shared_evidence else "No supplied evidence addresses this check."
            ),
            "source_documents": ["Registry.pdf — page 1"] if shared_evidence else [],
            "proposed_next_steps_and_questions": [],
        }
        assert reviewer is None
        return result

    monkeypatch.setattr(chat, "dataset_search", no_hits)
    monkeypatch.setattr(chat, "generate_json", assess)
    insight = await batch_audit(
        "example-startup",
        CHECKLIST,
        response_schema=DD_SCHEMA,
        llm_instructions=(
            "Use the supplied registry extract: Registry.pdf — page 1. "
            "The company is registered as an AG."
            if shared_evidence else "Assess supplied evidence; use Not Found if absent."
        ),
    )

    checks = json.loads(insight.content())["chapters"][0]["checks"]
    assert len(searches) == len(generations) == len(checks) == 2
    assert all(check["error"] is None for check in checks)
    assert all(
        check["result"]["status"] == ("Fine" if shared_evidence else "Not Found")
        for check in checks
    )


@pytest.mark.asyncio
async def test_structured_batch_audit_saves_json_insight(
    mock_env,
    monkeypatch,
):
    _indexed_dataset()
    calls = []

    async def fake_dataset_chat(**kwargs):
        calls.append(kwargs)
        return {
            "status": "Fine",
            "rationale": "Evidence found.",
            "source_documents": ["Registry.pdf — page 1"],
            "proposed_next_steps_and_questions": [],
        }

    monkeypatch.setattr(
        "lib.batch_audit.engine.dataset_chat_json",
        fake_dataset_chat,
    )
    monkeypatch.setattr(
        "lib.batch_audit.engine.llm_model",
        lambda: "google/gemini-2.5-pro",
    )

    insight = await batch_audit(
        dataset_name="example-startup",
        skill_name="dd_checks",
        checklist_markdown=CHECKLIST,
        llm_instructions="Use only supplied evidence and return JSON.",
        response_schema=DD_SCHEMA,
    )

    assert insight.filename == (
        "dd-checks-legal-due-diligence-gemini-2-5-pro.json"
    )
    assert insight.directory.endswith("/insights/batch-audit")
    audit = json.loads(insight.content())
    assert audit["checklist_title"] == "Legal Due Diligence"
    assert audit["chapters"][0]["checks"][0]["result"]["status"] == "Fine"
    assert len(calls) == 2
    assert calls[0]["queries"] == [
        "Is the company registered in the commercial registry?",
        "Is the company registered in the commercial registry?\n\n"
        "Relevant terminology: chamber of commerce, registration number",
    ]
    assert "chamber of commerce" not in calls[0]["prompt"]
    response_schema = calls[0]["schema"]
    assert response_schema["properties"]["status"]["enum"] == [
        "Not Found",
        "Critical",
        "Borderline",
        "Sufficient",
        "Fine",
    ]
    prefix = calls[0]["cacheable_prompt_prefix"]
    assert "Use only supplied evidence" in prefix
    assert "### CURRENT CHECK — START" not in prefix
    assert calls[0]["prompt"].index("### CURRENT CHECK — START") < (
        calls[0]["prompt"].index(
            "Is the company registered in the commercial registry?"
        )
    )


@pytest.mark.asyncio
async def test_structured_batch_audit_submits_checks_concurrently(
    mock_env,
    monkeypatch,
):
    from lib.batch_audit import engine

    _indexed_dataset()
    checklist = CHECKLIST + """

### Registered office

Is the registered office documented?
"""
    all_started = asyncio.Event()
    release = asyncio.Event()
    started = []

    async def fake_run_check(
        _dataset_name,
        check,
        _llm_instructions,
        _response_schema,
    ):
        started.append(check.number)
        if len(started) == 3:
            all_started.set()
        await release.wait()
        return {
            "result": {
                "status": "Pass",
                "rationale": f"Completed {check.number}.",
                "source_documents": [],
                "proposed_next_steps_and_questions": [],
            },
            "error": None,
        }

    monkeypatch.setattr(engine, "_run_check", fake_run_check)
    audit_task = asyncio.create_task(
        batch_audit(
            dataset_name="example-startup",
            skill_name="submission_ready",
            checklist_markdown=checklist,
            llm_instructions="Return JSON.",
            response_schema=AUDIT_SCHEMA,
        )
    )

    await all_started.wait()
    assert started == ["1.1", "1.2", "1.3"]

    release.set()
    insight = await audit_task
    checks = json.loads(insight.content())["chapters"][0]["checks"]
    assert [check["number"] for check in checks] == ["1.1", "1.2", "1.3"]


@pytest.mark.asyncio
async def test_structured_batch_audit_passes_schema_without_duplicate_reviewer(
    mock_env,
    monkeypatch,
):
    _indexed_dataset()
    calls = []

    async def fake_dataset_chat(**kwargs):
        calls.append(kwargs)
        invalid = {
            "status": "Maybe",
            "rationale": "Evidence found.",
            "source_documents": [],
            "proposed_next_steps_and_questions": [],
        }
        assert "reviewer" not in kwargs
        from lib.infrastructure.ai_text_generation.json import validate_json_schema
        with pytest.raises(ValueError, match="does not match"):
            validate_json_schema(invalid, kwargs["schema"])
        return {
            "status": "Pass",
            "rationale": "Evidence found.",
            "source_documents": [],
            "proposed_next_steps_and_questions": [],
        }

    monkeypatch.setattr(
        "lib.batch_audit.engine.dataset_chat_json",
        fake_dataset_chat,
    )

    insight = await batch_audit(
        dataset_name="example-startup",
        skill_name="submission_ready",
        checklist_markdown=CHECKLIST.replace(
            "### Legal form\n\nIs the current legal form established?\n",
            "",
        ),
        llm_instructions="Return JSON.",
        response_schema=AUDIT_SCHEMA,
    )

    check = json.loads(insight.content())["chapters"][0]["checks"][0]
    assert len(calls) == 1
    assert check["result"]["status"] == "Pass"
    assert check["error"] is None


@pytest.mark.asyncio
async def test_structured_batch_audit_records_absent_response_as_technical_failure(
    mock_env,
    monkeypatch,
):
    _indexed_dataset()
    calls = 0

    async def fake_dataset_chat(**_kwargs):
        nonlocal calls
        calls += 1
        return None

    monkeypatch.setattr(
        "lib.batch_audit.engine.dataset_chat_json",
        fake_dataset_chat,
    )

    insight = await batch_audit(
        dataset_name="example-startup",
        skill_name="submission_ready",
        checklist_markdown=CHECKLIST.replace(
            "### Legal form\n\nIs the current legal form established?\n",
            "",
        ),
        llm_instructions="Return JSON.",
        response_schema=AUDIT_SCHEMA,
    )

    check = json.loads(insight.content())["chapters"][0]["checks"][0]
    assert calls == 1
    assert check["result"] is None
    assert "returned no assessment" in check["error"]


@pytest.mark.asyncio
async def test_structured_batch_audit_records_exhausted_errors(
    mock_env,
    monkeypatch,
):
    _indexed_dataset()

    async def failing_dataset_chat(**_kwargs):
        raise RuntimeError("generate_json failed after 3 attempts")

    monkeypatch.setattr(
        "lib.batch_audit.engine.dataset_chat_json",
        failing_dataset_chat,
    )

    insight = await batch_audit(
        dataset_name="example-startup",
        skill_name="submission_ready",
        checklist_markdown=CHECKLIST,
        llm_instructions="Return JSON.",
        response_schema=AUDIT_SCHEMA,
    )

    checks = json.loads(insight.content())["chapters"][0]["checks"]
    assert all(check["result"] is None for check in checks)
    assert all("failed after 3 attempts" in check["error"] for check in checks)

    async def recovered_dataset_chat(**_kwargs):
        return {
            "status": "Pass",
            "rationale": "Provider recovered.",
            "source_documents": [],
            "proposed_next_steps_and_questions": [],
        }

    monkeypatch.setenv("RANKED_LLMS", "ollama/test-model:1b")
    monkeypatch.setattr(
        "lib.batch_audit.engine.dataset_chat_json",
        recovered_dataset_chat,
    )
    recovered = await batch_audit(
        dataset_name="example-startup",
        skill_name="submission_ready",
        checklist_markdown=CHECKLIST,
        llm_instructions="Return JSON.",
        response_schema=AUDIT_SCHEMA,
    )

    recovered_checks = json.loads(recovered.content())["chapters"][0]["checks"]
    assert all(check["result"]["status"] == "Pass" for check in recovered_checks)
    assert all(check["error"] is None for check in recovered_checks)


@pytest.mark.asyncio
async def test_structured_batch_audit_reuses_fresh_json(
    mock_env,
    monkeypatch,
):
    _indexed_dataset()
    monkeypatch.setenv("RANKED_LLMS", "ollama/test-model:1b")
    response = {
        "status": "Pass",
        "rationale": "Evidence found.",
        "source_documents": [],
        "proposed_next_steps_and_questions": [],
    }

    async def fake_dataset_chat(**_kwargs):
        return response

    monkeypatch.setattr(
        "lib.batch_audit.engine.dataset_chat_json",
        fake_dataset_chat,
    )
    kwargs = {
        "dataset_name": "example-startup",
        "skill_name": "submission_ready",
        "checklist_markdown": CHECKLIST,
        "llm_instructions": "Return JSON.",
        "response_schema": AUDIT_SCHEMA,
    }
    generated = await batch_audit(**kwargs)

    async def forbidden_dataset_chat(**_kwargs):
        raise AssertionError("A fresh audit must be reused.")

    monkeypatch.setattr(
        "lib.batch_audit.engine.dataset_chat_json",
        forbidden_dataset_chat,
    )
    reused = await batch_audit(**kwargs)

    assert reused.path == generated.path


FLEXIBLE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "score": {"type": "integer", "minimum": 1, "maximum": 5, "title": "Evidence score"},
        "decision": {"type": "string", "enum": ["Proceed", "Investigate"]},
        "findings": {"type": "array", "items": {"type": "object"}},
    },
    "required": ["score", "decision", "findings"],
}
FLEXIBLE_RESULT = {"score": 4, "decision": "Proceed", "findings": [{"source": "deck.pdf"}]}


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [
    {"decision": "Proceed", "findings": []},
    {"score": 6, "decision": "Proceed", "findings": []},
    {"score": 4, "decision": "Maybe", "findings": []},
    {"score": "4", "decision": "Proceed", "findings": []},
    {**FLEXIBLE_RESULT, "unexpected": True},
])
async def test_flexible_audit_uses_generate_json_schema_correction(mock_env, monkeypatch, invalid):
    """Exercise real generation validation/retry through audit and dataset chat."""
    from copy import deepcopy
    from unittest.mock import AsyncMock
    from lib.infrastructure.ai_text_generation import generation
    from lib.batch_audit.rendering import json_to_markdown_table

    _indexed_dataset()
    chat = importlib.import_module("skills.dataset_chat.dataset_chat")
    monkeypatch.setattr(chat, "dataset_search", AsyncMock(return_value=[]))
    request = AsyncMock(side_effect=[
        json.dumps(invalid),
        json.dumps({"reasoning": "Correct the schema violation.", **FLEXIBLE_RESULT}),
    ])
    monkeypatch.setattr(generation, "_request_text_waiting_out_rate_limits", request)
    schema = deepcopy(FLEXIBLE_SCHEMA)
    insight = await batch_audit(
        "example-startup", "# Audit\n## Evidence\n### Review\nAssess the evidence.",
        response_schema=schema, llm_instructions="Assess supplied evidence on a scale of 1–5.",
    )
    audit = json.loads(insight.content())
    assert request.await_count == 2
    assert "does not match the schema" in request.await_args.kwargs["prompt"]
    assert audit["response_schema"] == schema == FLEXIBLE_SCHEMA
    assert audit["chapters"][0]["checks"][0] == {
        "number": "1.1", "check": "Review", "result": FLEXIBLE_RESULT, "error": None,
    }
    table = json_to_markdown_table(insight)
    assert "| No | Check | Evidence score | Decision | Findings |" in table
    assert '| 1.1 | Review | 4 | Proceed | {"source": "deck.pdf"} |' in table


@pytest.mark.asyncio
async def test_schema_and_prompt_changes_invalidate_audit_cache(mock_env, monkeypatch):
    from copy import deepcopy
    from unittest.mock import AsyncMock

    _indexed_dataset()
    monkeypatch.setenv("RANKED_LLMS", "ollama/test-model:1b")
    generate = AsyncMock(return_value=FLEXIBLE_RESULT)
    monkeypatch.setattr("lib.batch_audit.engine.dataset_chat_json", generate)
    kwargs = dict(
        dataset_name="example-startup", checklist_markdown=CHECKLIST,
        response_schema=deepcopy(FLEXIBLE_SCHEMA), llm_instructions="Assess evidence.",
    )
    first = await batch_audit(**kwargs)
    await batch_audit(**kwargs)
    assert generate.await_count == 2
    kwargs["response_schema"]["properties"]["score"]["maximum"] = 10
    second = await batch_audit(**kwargs)
    assert generate.await_count == 4
    assert second.path == first.path
    kwargs["llm_instructions"] = "Assess evidence conservatively."
    await batch_audit(**kwargs)
    assert generate.await_count == 6


@pytest.mark.asyncio
@pytest.mark.parametrize("schema", [None, {}, {"type": "array"}, {"type": "object", "properties": {"score": {"type": "invalid"}}}])
async def test_invalid_audit_schema_fails_before_retrieval(mock_env, monkeypatch, schema):
    from unittest.mock import AsyncMock

    retrieve = AsyncMock()
    monkeypatch.setattr("lib.batch_audit.engine.dataset_chat_json", retrieve)
    with pytest.raises(ValueError):
        await batch_audit("example-startup", CHECKLIST, response_schema=schema, llm_instructions="Assess.")
    retrieve.assert_not_awaited()


@pytest.mark.asyncio
async def test_manual_audit_takes_precedence_without_regeneration(mock_env, monkeypatch):
    from unittest.mock import AsyncMock
    from lib.insights import InsightFile

    _indexed_dataset()
    generate = AsyncMock(return_value=FLEXIBLE_RESULT)
    monkeypatch.setattr("lib.batch_audit.engine.dataset_chat_json", generate)
    kwargs = dict(
        dataset_name="example-startup", checklist_markdown=CHECKLIST,
        response_schema=FLEXIBLE_SCHEMA, llm_instructions="Assess evidence.",
    )
    generated = await batch_audit(**kwargs)
    audit = json.loads(generated.content())
    audit["chapters"][0]["checks"][0]["result"]["score"] = 2
    manual = InsightFile(
        "example-startup", "batch_audit", "manual",
        identifier="batch_audit-Legal Due Diligence", subdir=True, extension="json",
    )
    manual.save(json.dumps(audit))
    selected = await batch_audit(**kwargs)
    assert selected.path == manual.path
    assert generate.await_count == 2
    assert json.loads(selected.content())["chapters"][0]["checks"][0]["result"]["score"] == 2


@pytest.mark.asyncio
async def test_new_audit_does_not_revalidate_before_saving(mock_env, monkeypatch):
    from unittest.mock import AsyncMock, Mock

    _indexed_dataset()
    monkeypatch.setattr(
        "lib.batch_audit.engine.dataset_chat_json",
        AsyncMock(return_value=FLEXIBLE_RESULT),
    )
    validate = Mock(side_effect=AssertionError("Generation already validated the response"))
    monkeypatch.setattr("lib.batch_audit.engine.validate_audit_document", validate)
    insight = await batch_audit(
        "example-startup", CHECKLIST,
        response_schema=FLEXIBLE_SCHEMA, llm_instructions="Assess evidence.",
    )
    assert insight.exists()
    validate.assert_not_called()
