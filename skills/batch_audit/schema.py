from __future__ import annotations

from typing import Any


AUDIT_SCHEMA_VERSION = 1
AUDIT_FIELDS = {
    "number",
    "check",
    "status",
    "rationale",
    "source_documents",
    "proposed_next_steps_and_questions",
    "error",
}


def validate_audit_document(audit: Any) -> dict[str, Any]:
    """Validate the common JSON contract shared by all audit skills."""
    if not isinstance(audit, dict):
        raise ValueError("Audit JSON must be an object.")
    if audit.get("schema_version") != AUDIT_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported audit schema version: {audit.get('schema_version')!r}."
        )
    for field in (
        "skill",
        "checklist_title",
        "dataset",
        "model",
        "generated_at",
    ):
        if not isinstance(audit.get(field), str) or not audit[field].strip():
            raise ValueError(f"Audit field {field!r} must be a non-empty string.")

    status_scale = audit.get("status_scale")
    if (
        not isinstance(status_scale, list)
        or not status_scale
        or not all(isinstance(value, str) and value for value in status_scale)
    ):
        raise ValueError("Audit status_scale must be a non-empty string list.")

    chapters = audit.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise ValueError("Audit chapters must be a non-empty list.")
    for chapter in chapters:
        if not isinstance(chapter, dict):
            raise ValueError("Each audit chapter must be an object.")
        if not isinstance(chapter.get("number"), str):
            raise ValueError("Each audit chapter requires a string number.")
        if not isinstance(chapter.get("title"), str) or not chapter["title"]:
            raise ValueError("Each audit chapter requires a title.")
        checks = chapter.get("checks")
        if not isinstance(checks, list) or not checks:
            raise ValueError("Each audit chapter requires checks.")
        for check in checks:
            _validate_check(check, status_scale)
    return audit


def audit_errors(audit: dict[str, Any]) -> list[dict[str, Any]]:
    """Return checks that could not be completed technically."""
    validate_audit_document(audit)
    return [
        check
        for chapter in audit["chapters"]
        for check in chapter["checks"]
        if check["error"] is not None
    ]


def _validate_check(check: Any, status_scale: list[str]) -> None:
    if not isinstance(check, dict):
        raise ValueError("Each audit check must be an object.")
    missing = AUDIT_FIELDS - check.keys()
    if missing:
        raise ValueError(
            "Audit check is missing fields: " + ", ".join(sorted(missing))
        )
    if not isinstance(check["number"], str) or not check["number"]:
        raise ValueError("Audit check number must be a non-empty string.")
    if not isinstance(check["check"], str) or not check["check"]:
        raise ValueError("Audit check name must be a non-empty string.")
    error = check["error"]
    if error is not None and (not isinstance(error, str) or not error):
        raise ValueError("Audit check error must be null or a non-empty string.")
    if error is None:
        if check["status"] not in status_scale:
            raise ValueError(
                f"Invalid audit status {check['status']!r}; expected {status_scale}."
            )
        if not isinstance(check["rationale"], str):
            raise ValueError("Audit rationale must be a string.")
    elif check["status"] is not None:
        raise ValueError("A failed audit check must have a null status.")
    for field in ("source_documents", "proposed_next_steps_and_questions"):
        value = check[field]
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            raise ValueError(f"Audit field {field!r} must be a string list.")
