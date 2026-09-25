import json
from pathlib import Path
from types import SimpleNamespace

from lib.batch_audit.rendering import ranked_checks_to_markdown_table

DD_SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "config/dd_checks/audit_response_schema.json").read_text()
)


def _audit(title: str, checks: list[tuple[str, str, int | None]]) -> SimpleNamespace:
    """Build a fake audit insight. An importance of None marks a technical error."""
    audit = {
        "schema_version": 2,
        "skill": "dd_checks",
        "checklist_title": title,
        "dataset": "example-startup",
        "model": "ollama/test_model:1b",
        "generated_at": "2026-09-25T00:00:00Z",
        "response_schema": DD_SCHEMA,
        "chapters": [{
            "number": checks[0][0].rsplit(".", 1)[0],
            "title": title,
            "checks": [
                {
                    "number": number,
                    "check": name,
                    "result": None if importance is None else {
                        "status": "Critical",
                        "importance": importance,
                        "rationale": f"Rationale for {name}.",
                        "source_documents": ["deck.pdf — page 2"],
                        "proposed_next_steps_and_questions": [],
                    },
                    "error": "Model failed" if importance is None else None,
                }
                for number, name, importance in checks
            ],
        }],
    }
    return SimpleNamespace(content=lambda: json.dumps(audit))


def _row_numbers(table: str) -> list[str]:
    return [line.split(" | ")[1] for line in table.splitlines()[2:]]


def test_ranked_table_sorts_checks_from_all_audits_by_importance():
    audits = [
        _audit("3 Team", [("3.1.1", "Team overview", 4), ("3.1.2", "Founder IP", 9)]),
        _audit("7 Product", [("7.1.1", "Prototype", 7), ("7.1.2", "Patents", 9)]),
    ]

    table = ranked_checks_to_markdown_table(audits, "importance", minimum=1, limit=10)

    assert table.splitlines()[0] == (
        "| Importance | No | Check | Status | Rationale | Source documents "
        "| Proposed next steps and questions |"
    )
    # Equal importance keeps the order of the checklists and their checks.
    assert _row_numbers(table) == ["3.1.2", "7.1.2", "7.1.1", "3.1.1"]
    assert "| 9 | 3.1.2 | Founder IP | Critical | Rationale for Founder IP. |" in table


def test_ranked_table_applies_minimum_and_limit():
    audits = [_audit("3 Team", [
        ("3.1.1", "Low", 5),
        ("3.1.2", "High", 8),
        ("3.1.3", "Higher", 9),
        ("3.1.4", "Threshold", 6),
    ])]

    table = ranked_checks_to_markdown_table(audits, "importance", minimum=6, limit=2)

    assert _row_numbers(table) == ["3.1.3", "3.1.2"]


def test_ranked_table_skips_failed_checks_and_returns_empty_text_without_rows():
    audits = [_audit("3 Team", [("3.1.1", "Failed", None), ("3.1.2", "Minor", 2)])]

    assert ranked_checks_to_markdown_table(audits, "importance", minimum=6, limit=5) == ""
    table = ranked_checks_to_markdown_table(audits, "importance", minimum=1, limit=5)
    assert _row_numbers(table) == ["3.1.2"]
