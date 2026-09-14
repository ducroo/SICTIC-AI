from __future__ import annotations

from typing import Any

from lib.infrastructure.ai_text_generation.json import (
    copy_schema,
    validate_json_schema,
    validate_schema,
)
from lib.infrastructure.configuration import load_repository_config


AUDIT_SCHEMA_VERSION = 2


def validate_response_schema(schema: Any) -> None:
    """Require an object schema with named properties for assessment and rendering."""
    validate_json_schema(schema, {
        "type": "object",
        "required": ["type", "properties"],
        "properties": {"type": {"const": "object"}, "properties": {"type": "object"}},
    }, label="Audit response schema")
    validate_schema(schema)


def validate_audit_document(
    audit: Any, *, require_complete: bool = False,
) -> dict[str, Any]:
    """Validate stored JSON with the shared validator; optionally require success."""
    response_schema = audit.get("response_schema") if isinstance(audit, dict) else None
    validate_response_schema(response_schema)
    schema = copy_schema(load_repository_config("batch_audit", "audit_schema"))
    schema["properties"]["schema_version"] = {"const": AUDIT_SCHEMA_VERSION}
    assessment = copy_schema(response_schema)
    # Keep caller-local JSON references rooted in the assessment schema when
    # embedding it in the larger document schema.
    assessment.setdefault("$id", "urn:sictic:batch-audit:assessment")
    assessment.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
    schema["$defs"]["assessment"] = assessment
    if require_complete:
        schema["$defs"]["check"]["properties"]["error"] = {"type": "null"}
    validate_json_schema(audit, schema, label="Audit")
    return audit
