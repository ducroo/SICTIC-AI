from pathlib import Path
import json

import pytest

from lib.batch_audit.checklist import parse_checklist
from lib.batch_audit.rendering import json_to_markdown_table
from lib.batch_audit.schema import validate_audit_document

AUDIT_SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "config/submission_ready/audit_response_schema.json").read_text()
)


def test_parse_structured_markdown_checklist():
    checklist = parse_checklist(
        """# Company Due Diligence

## Legal

### Chamber of commerce registration

Is the company registered in the appropriate commercial registry?

Use an explicit registration number as sufficient evidence.

**Keywords:** commercial registry, chamber of commerce,
company registration

### Legal form

Is the current legal form clearly established?

## Ownership

### Shareholder register

Is a current shareholder register available?

**Keywords:** cap table; ownership
"""
    )

    assert checklist.title == "Company Due Diligence"
    assert [chapter.number for chapter in checklist.chapters] == ["1", "2"]
    first = checklist.chapters[0].checks[0]
    assert first.number == "1.1"
    assert first.name == "Chamber of commerce registration"
    assert "sufficient evidence" in first.description
    assert first.keywords == [
        "commercial registry",
        "chamber of commerce",
        "company registration",
    ]
    assert checklist.chapters[0].checks[1].number == "1.2"
    assert checklist.chapters[1].checks[0].number == "2.1"


def test_numbered_checklist_title_prefixes_chapters_and_checks():
    checklist = parse_checklist(
        """# 2 Corporation-General

## Governance

### Entity mapping

Is the corporate structure documented?

## Ownership

### Shareholder register

Is a current shareholder register available?
"""
    )

    assert [chapter.number for chapter in checklist.chapters] == ["2.1", "2.2"]
    assert checklist.chapters[0].checks[0].number == "2.1.1"
    assert checklist.chapters[1].checks[0].number == "2.2.1"


@pytest.mark.parametrize(
    ("markdown", "message"),
    [
        ("## Legal\n### Registration\nDescription", "level-one title"),
        ("# Audit\n### Registration\nDescription", "level-two chapter"),
        ("# Audit\n## Legal", "has no checks"),
        ("# Audit\n## Legal\n### Registration", "has no description"),
    ],
)
def test_parse_structured_markdown_rejects_invalid_structure(markdown, message):
    with pytest.raises(ValueError, match=message):
        parse_checklist(markdown)


def _audit_document():
    return {
        "schema_version": 2,
        "skill": "submission_ready",
        "checklist_title": "Submission Readiness",
        "dataset": "example-startup",
        "model": "google/gemini-2.5-pro",
        "generated_at": "2026-08-06T10:00:00Z",
        "response_schema": AUDIT_SCHEMA,
        "chapters": [
            {
                "number": "1",
                "title": "Submission provenance",
                "checks": [
                    {
                        "number": "1.1",
                        "check": "Founder submission",
                        "result": {
                            "status": "Pass",
                            "rationale": "Founder evidence | confirmed.",
                            "source_documents": ["Dealum — Contact"],
                            "proposed_next_steps_and_questions": [],
                        },
                        "error": None,
                    },
                    {
                        "number": "1.2",
                        "check": "Pitch deck",
                        "result": None,
                        "error": "LLM request failed",
                    },
                ],
            }
        ],
    }


def test_validate_common_audit_contract_rejects_unknown_status():
    audit = _audit_document()
    audit["chapters"][0]["checks"][0]["result"]["status"] = "Maybe"

    with pytest.raises(ValueError, match="does not match the schema"):
        validate_audit_document(audit)


def test_json_to_markdown_table_uses_common_columns():
    class FakeInsight:
        def content(self):
            return json.dumps(_audit_document())

    table = json_to_markdown_table(FakeInsight())

    assert table.startswith("**Model:** gemini-2.5-pro")
    assert "| No | Check | Status | Rationale | Source documents |" in table
    assert (
        "| 1.1 | Founder submission | Pass | Founder evidence \\| confirmed. |"
        in table
    )
    assert "| 1.2 | Pitch deck |  |  |  |  | LLM request failed |" in table


@pytest.mark.parametrize("mutation", [
    lambda audit: audit.update(schema_version=1),
    lambda audit: audit["chapters"][0]["checks"][0]["result"].pop("rationale"),
    lambda audit: audit["chapters"][0]["checks"][0]["result"].update(extra=True),
    lambda audit: audit["chapters"][0]["checks"][1].update(result={}),
    lambda audit: audit["chapters"][0]["checks"][0].pop("error"),
])
def test_stored_audit_rejects_invalid_results_and_old_format(mutation):
    audit = _audit_document()
    mutation(audit)
    with pytest.raises(ValueError):
        validate_audit_document(audit)


def test_renderer_handles_optional_nested_and_additional_fields():
    audit = _audit_document()
    audit["response_schema"] = {
        "type": "object",
        "properties": {"details": {"title": "Evidence details"}, "optional": True},
    }
    audit["chapters"][0]["checks"][0]["result"] = {
        "details": [{"source": "A|B", "page": 2}, "Another source"],
        "extra": False,
    }
    class FakeInsight:
        def content(self):
            return json.dumps(audit)
    table = json_to_markdown_table(FakeInsight())
    assert "| Evidence details | Optional | Extra | Error |" in table
    assert '{"source": "A\\|B", "page": 2}<br>Another source |  | false |' in table


def test_completed_schema_rejects_recorded_failure_but_accepts_success():
    audit = _audit_document()
    assert validate_audit_document(audit) is audit
    with pytest.raises(ValueError, match=r"checks\[1\].error.*LLM request failed"):
        validate_audit_document(audit, require_complete=True)
    audit["chapters"][0]["checks"].pop()
    assert validate_audit_document(audit, require_complete=True) is audit
    # Completion requirements must not mutate the shared envelope configuration.
    assert validate_audit_document(_audit_document())


@pytest.mark.parametrize("schema_id", [None, "urn:test:custom-assessment"])
def test_embedded_assessment_preserves_local_schema_references(schema_id):
    from copy import deepcopy

    audit = _audit_document()
    response_schema = {
        "type": "object",
        "properties": {"score": {"$ref": "#/$defs/rating"}},
        "required": ["score"],
        "$defs": {"rating": {"type": "integer", "minimum": 1, "maximum": 5}},
    }
    if schema_id:
        response_schema["$id"] = schema_id
    original_schema = deepcopy(response_schema)
    audit["response_schema"] = response_schema
    audit["chapters"][0]["checks"] = [{
        "number": "1.1", "check": "Score", "result": {"score": 3}, "error": None,
    }]
    validate_audit_document(audit, require_complete=True)
    assert response_schema == original_schema
    audit["chapters"][0]["checks"][0]["result"]["score"] = 6
    with pytest.raises(ValueError, match=r"result.score.*maximum"):
        validate_audit_document(audit, require_complete=True)
