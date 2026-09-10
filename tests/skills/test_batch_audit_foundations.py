import json

import pytest

from lib.batch_audit.checklist import parse_checklist
from lib.batch_audit.rendering import json_to_markdown_table
from lib.batch_audit.schema import validate_audit_document


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
        "schema_version": 1,
        "skill": "submission_ready",
        "checklist_title": "Submission Readiness",
        "dataset": "example-startup",
        "model": "google/gemini-2.5-pro",
        "generated_at": "2026-08-06T10:00:00Z",
        "status_scale": ["Pass", "Fail", "Unclear"],
        "chapters": [
            {
                "number": "1",
                "title": "Submission provenance",
                "checks": [
                    {
                        "number": "1.1",
                        "check": "Founder submission",
                        "status": "Pass",
                        "rationale": "Founder evidence | confirmed.",
                        "source_documents": ["Dealum — Contact"],
                        "proposed_next_steps_and_questions": [],
                        "error": None,
                    },
                    {
                        "number": "1.2",
                        "check": "Pitch deck",
                        "status": None,
                        "rationale": None,
                        "source_documents": [],
                        "proposed_next_steps_and_questions": [],
                        "error": "LLM request failed",
                    },
                ],
            }
        ],
    }


def test_validate_common_audit_contract_rejects_unknown_status():
    audit = _audit_document()
    audit["chapters"][0]["checks"][0]["status"] = "Maybe"

    with pytest.raises(ValueError, match="Invalid audit status"):
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
    assert "| 1.2 | Pitch deck | Error | LLM request failed |" in table
