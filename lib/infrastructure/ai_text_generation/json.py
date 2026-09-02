"""Technical JSON repair and JSON Schema handling."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from lib.infrastructure.configuration import load_repository_config
from lib.infrastructure.logging import get_logger


logger = get_logger(__name__)

_VALID_JSON_ESCAPES = {'"', "\\", "/", "b", "f", "n", "r", "t"}
TEMPORARY_REASONING_FIELD = "reasoning"
TEMPORARY_RESULT_FIELD = "result"
TEMPORARY_REASONING_DESCRIPTION = (
    "Brief working notes that analyze the supplied evidence and constraints "
    "before producing the requested business fields."
)


def copy_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return an isolated schema suitable for runtime specialization."""
    return deepcopy(schema)


def add_temporary_reasoning_field(
    schema: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Put an ephemeral reasoning field before the requested response.

    Object schemas are extended directly. Other schemas, and object schemas
    that already own a ``reasoning`` property, are wrapped under ``result``.
    The returned flag tells the caller whether unwrapping is required.
    """
    schema = copy_schema(schema)
    reasoning = {
        "type": "string",
        "description": TEMPORARY_REASONING_DESCRIPTION,
    }
    properties = schema.get("properties")
    if (
        schema.get("type") == "object"
        and isinstance(properties, dict)
        and TEMPORARY_REASONING_FIELD not in properties
    ):
        schema["properties"] = {
            TEMPORARY_REASONING_FIELD: reasoning,
            **properties,
        }
        required = list(schema.get("required") or [])
        schema["required"] = [
            TEMPORARY_REASONING_FIELD,
            *(
                field
                for field in required
                if field != TEMPORARY_REASONING_FIELD
            ),
        ]
        return schema, False
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            TEMPORARY_REASONING_FIELD: reasoning,
            TEMPORARY_RESULT_FIELD: schema,
        },
        "required": [TEMPORARY_REASONING_FIELD, TEMPORARY_RESULT_FIELD],
    }, True


def remove_temporary_reasoning(
    value: dict | list,
    *,
    wrapped: bool,
) -> dict | list:
    """Remove the temporary field and return only the requested response."""
    if not isinstance(value, dict):
        raise ValueError("Temporary reasoning response must be a JSON object.")
    if wrapped:
        result = value.get(TEMPORARY_RESULT_FIELD)
        if not isinstance(result, (dict, list)):
            raise ValueError(
                "Temporary reasoning response does not contain a JSON result."
            )
        return result
    output = dict(value)
    output.pop(TEMPORARY_REASONING_FIELD, None)
    return output


def schema_text(schema: dict[str, Any]) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=2)


def schema_prompt_block(schema: dict[str, Any]) -> str:
    """Render the configured instructions for a schema response."""
    template = load_repository_config(
        "structured_output",
        "json_response_instructions",
    )
    placeholder = "{{response_schema}}"
    if template.count(placeholder) != 1:
        raise ValueError(
            "structured_output.json_response_instructions must contain "
            "{{response_schema}} exactly once."
        )
    return template.replace(placeholder, schema_text(schema))


def json_schema_response_format(
    schema: dict[str, Any],
    *,
    name: str = "structured_response",
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


def validate_schema(schema: dict[str, Any]) -> None:
    """Reject an invalid schema before making a provider request."""
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise ValueError(f"Invalid JSON response schema: {error}") from error


def validate_json_schema(
    value: object,
    schema: dict[str, Any],
    *,
    label: str = "AI response",
) -> None:
    """Validate a value and report a readable JSON path on failure."""
    try:
        Draft202012Validator(schema).validate(value)
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
    label: str = "AI response",
) -> dict | list:
    parsed = repair_json_payload(raw_response)
    validate_json_schema(parsed, schema, label=label)
    return parsed


def repair_json_payload(raw_output: str) -> dict | list:
    """Extract JSON and repair only unambiguous technical syntax errors."""
    if not raw_output:
        raise ValueError("Empty response from AI model.")

    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_output)
    if fenced:
        try:
            return _loads_with_repairs(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass

    start_brace = raw_output.find("{")
    start_bracket = raw_output.find("[")
    if start_brace != -1 and (
        start_bracket == -1 or start_brace < start_bracket
    ):
        start_index = start_brace
        end_index = raw_output.rfind("}")
    elif start_bracket != -1:
        start_index = start_bracket
        end_index = raw_output.rfind("]")
    else:
        raise ValueError("AI response does not contain a JSON object or array.")

    if end_index < start_index:
        raise ValueError("AI response contains incomplete JSON.")
    try:
        return _loads_with_repairs(raw_output[start_index : end_index + 1])
    except json.JSONDecodeError as error:
        raise ValueError(f"AI response contains invalid JSON: {error}") from error


def _loads_with_repairs(json_text: str) -> dict | list:
    try:
        return json.loads(json_text)
    except json.JSONDecodeError as first_error:
        repairs: list[str] = []
        repaired = _escape_invalid_backslashes(json_text)
        if repaired != json_text:
            repairs.append("invalid backslashes")
        without_trailing_commas = _remove_trailing_commas(repaired)
        if without_trailing_commas != repaired:
            repairs.append("trailing commas")
        if not repairs:
            raise first_error
        try:
            parsed = json.loads(without_trailing_commas)
        except json.JSONDecodeError:
            raise first_error
        logger.warning(
            "Repaired malformed JSON output (%s)",
            ", ".join(repairs),
        )
        return parsed


def _escape_invalid_backslashes(json_text: str) -> str:
    repaired: list[str] = []
    in_string = False
    escaped = False
    index = 0
    while index < len(json_text):
        char = json_text[index]
        if not in_string:
            repaired.append(char)
            if char == '"':
                in_string = True
            index += 1
            continue
        if escaped:
            if char in _VALID_JSON_ESCAPES:
                repaired.append(char)
            elif char == "u" and re.fullmatch(
                r"[0-9a-fA-F]{4}",
                json_text[index + 1 : index + 5],
            ):
                repaired.append(char)
            else:
                repaired.extend(("\\", char))
            escaped = False
            index += 1
            continue
        if char == "\\":
            repaired.append(char)
            escaped = True
            index += 1
            continue
        if char == '"':
            in_string = False
        repaired.append(char)
        index += 1
    if escaped:
        repaired.append("\\")
    return "".join(repaired)


def _remove_trailing_commas(json_text: str) -> str:
    repaired: list[str] = []
    in_string = False
    escaped = False
    index = 0
    while index < len(json_text):
        char = json_text[index]
        if in_string:
            repaired.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            repaired.append(char)
            index += 1
            continue
        if char == ",":
            next_index = index + 1
            while (
                next_index < len(json_text)
                and json_text[next_index].isspace()
            ):
                next_index += 1
            if (
                next_index < len(json_text)
                and json_text[next_index] in "}]"
            ):
                index += 1
                continue
        repaired.append(char)
        index += 1
    return "".join(repaired)
