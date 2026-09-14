from __future__ import annotations

import json
from typing import Any

from lib.insights import InsightFile
from lib.batch_audit.schema import validate_audit_document


def _table_cell(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, list):
        return "<br>".join(_table_cell(item) for item in value) or "None"
    if isinstance(value, (dict, bool)):
        value = json.dumps(value, ensure_ascii=False)
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _field_title(field: str, definition: Any) -> str:
    title = definition.get("title") if isinstance(definition, dict) else None
    return _table_cell(title if title else field.replace("_", " ").capitalize())


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def json_to_markdown_table(insight: InsightFile) -> str:
    """Render assessment properties in schema order, with separate technical errors."""
    audit = validate_audit_document(json.loads(insight.content()))
    properties = audit["response_schema"]["properties"]
    fields = list(properties)
    checks = [check for chapter in audit["chapters"] for check in chapter["checks"]]
    # Schemas may permit additional fields; do not silently discard their values.
    fields.extend(sorted({
        key for check in checks for key in (check["result"] or {})
        if key not in properties
    }))
    show_errors = any(check["error"] is not None for check in checks)
    headers = ["No", "Check"] + [
        _field_title(field, properties.get(field))
        for field in fields
    ]
    if show_errors:
        headers.append("Error")
    lines = [
        f"**Model:** {_table_cell(audit['model'].rsplit('/', 1)[-1])}",
        "",
        _row(headers),
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for chapter in audit["chapters"]:
        lines.append(_row([
            _table_cell(chapter["number"]),
            f"**{_table_cell(chapter['title'])}**",
            *([""] * (len(headers) - 2)),
        ]))
        for check in chapter["checks"]:
            result = check["result"]
            cells = [_table_cell(check["number"]), _table_cell(check["check"])]
            cells.extend(
                _table_cell(result[field]) if result is not None and field in result else ""
                for field in fields
            )
            if show_errors:
                cells.append(_table_cell(check["error"]) if check["error"] is not None else "")
            lines.append(_row(cells))
    return "\n".join(lines)
