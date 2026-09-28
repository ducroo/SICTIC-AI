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


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def ranked_checks_to_markdown_table(
    insights: list[InsightFile],
    rank_field: str,
    *,
    minimum: float,
    limit: int,
) -> str:
    """Render checks from several audits in one table, highest `rank_field` value first.

    Lists successful checks whose numeric `rank_field` value is at least
    `minimum`, at most `limit` of them. Checks with equal values keep their
    checklist order. Returns an empty string when no check qualifies.
    """
    audits = [validate_audit_document(json.loads(insight.content())) for insight in insights]
    # Collect every schema field once, in schema order, across all audits.
    properties: dict[str, Any] = {}
    for audit in audits:
        for field, definition in audit["response_schema"]["properties"].items():
            properties.setdefault(field, definition)
    ranked_checks = [
        check
        for audit in audits
        for chapter in audit["chapters"]
        for check in chapter["checks"]
        if check["result"] is not None
        and _is_number(check["result"].get(rank_field))
        and check["result"][rank_field] >= minimum
    ]
    # Python's sort is stable, so equal values keep their checklist order.
    ranked_checks.sort(key=lambda check: check["result"][rank_field], reverse=True)
    ranked_checks = ranked_checks[:limit]
    if not ranked_checks:
        return ""

    fields = [field for field in properties if field != rank_field]
    # Schemas may permit additional fields; do not silently discard their values.
    fields.extend(sorted({
        key for check in ranked_checks for key in check["result"]
        if key not in properties and key != rank_field
    }))
    headers = [
        _field_title(rank_field, properties.get(rank_field)),
        "No",
        "Check",
        *(_field_title(field, properties.get(field)) for field in fields),
    ]
    lines = [_row(headers), "|" + "|".join("---" for _ in headers) + "|"]
    for check in ranked_checks:
        result = check["result"]
        lines.append(_row([
            _table_cell(result[rank_field]),
            _table_cell(check["number"]),
            _table_cell(check["check"]),
            *(_table_cell(result[field]) if field in result else "" for field in fields),
        ]))
    return "\n".join(lines)
