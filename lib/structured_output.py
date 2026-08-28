"""Shared JSON Schema handling for structured LLM responses."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from lib.json_parser import repair_json_payload


def copy_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return an isolated schema suitable for runtime specialization."""
    return deepcopy(schema)


def schema_text(schema: dict[str, Any]) -> str:
    """Render a schema consistently for inclusion in an LLM prompt."""
    return json.dumps(schema, ensure_ascii=False, indent=2)


def schema_prompt_block(schema: dict[str, Any]) -> str:
    """Render the shared, configured instructions for a schema response."""
    from skills.config_load.config_load import config_load

    template = config_load()["structured_output"][
        "json_response_instructions"
    ]
    placeholder = "{{response_schema}}"
    if template.count(placeholder) != 1:
        raise ValueError(
            "structured_output.json_response_instructions must contain "
            "{{response_schema}} exactly once."
        )
    return template.replace(placeholder, schema_text(schema))


def is_llm_timeout(error: BaseException) -> bool:
    """Return whether an exception is a provider, HTTP, or gateway timeout."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, TimeoutError):
            return True
        name = type(current).__name__.lower()
        message = str(current).lower()
        if "timeout" in name or "timed out" in message:
            return True
        current = current.__cause__ or current.__context__
    return False


def is_retryable_structured_error(error: BaseException) -> bool:
    """Retry schema/parse failures only; never retry timeouts or transport."""
    return isinstance(error, ValueError) and not is_llm_timeout(error)


def structured_correction_feedback(error: BaseException) -> str:
    return (
        "\n\n### CORRECTION REQUIRED\n\n"
        f"Your previous response was invalid: {error}\n"
        "Try again and return only a JSON object matching the schema."
    )


def json_schema_response_format(
    name: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    """Build LiteLLM's strict JSON Schema response-format payload."""
    normalized_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_")
    if not normalized_name:
        raise ValueError("A structured response format requires a name.")
    return {
        "type": "json_schema",
        "json_schema": {
            "name": normalized_name,
            "strict": True,
            "schema": schema,
        },
    }


def validate_json_schema(
    value: object,
    schema: dict[str, Any],
    *,
    label: str = "LLM response",
) -> None:
    """Validate a value and report a readable JSON path on failure."""
    try:
        validator = Draft202012Validator(schema)
        validator.check_schema(schema)
        validator.validate(value)
    except SchemaError as error:
        raise ValueError(f"Invalid {label} schema: {error}") from error
    except ValidationError as error:
        path = "$"
        for part in error.absolute_path:
            path += f"[{part}]" if isinstance(part, int) else f".{part}"
        raise ValueError(
            f"{label} does not match the schema at {path}: {error.message}"
        ) from error


def parse_json_response(
    raw_response: str,
    schema: dict[str, Any],
    *,
    label: str = "LLM response",
) -> dict | list:
    """Repair an LLM response as JSON, then validate it against a schema."""
    parsed = repair_json_payload(raw_response)
    validate_json_schema(parsed, schema, label=label)
    return parsed
