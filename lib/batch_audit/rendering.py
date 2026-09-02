from __future__ import annotations

import json
from typing import Any

from lib.insights import InsightFile
from lib.batch_audit.schema import validate_audit_document


def _table_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _list_cell(values: list[str]) -> str:
    return "<br>".join(_table_cell(value) for value in values) or "None"


def json_to_markdown_table(insight: InsightFile) -> str:
    """Render a structured audit Insight as a common Markdown table."""
    audit = validate_audit_document(json.loads(insight.content()))
    lines = [
        f"**Model:** {_table_cell(audit['model'].rsplit('/', 1)[-1])}",
        "",
        "| No | Check | Status | Rationale | Source documents | "
        "Proposed next steps and questions |",
        "|---|---|---|---|---|---|",
    ]
    for chapter in audit["chapters"]:
        lines.append(
            f"| {_table_cell(chapter['number'])} | "
            f"**{_table_cell(chapter['title'])}** | | | | |"
        )
        for check in chapter["checks"]:
            status = check["status"] if check["error"] is None else "Error"
            rationale = (
                check["rationale"]
                if check["error"] is None
                else check["error"]
            )
            lines.append(
                f"| {_table_cell(check['number'])} | "
                f"{_table_cell(check['check'])} | {_table_cell(status)} | "
                f"{_table_cell(rationale)} | "
                f"{_list_cell(check['source_documents'])} | "
                f"{_list_cell(check['proposed_next_steps_and_questions'])} |"
            )
    return "\n".join(lines)
