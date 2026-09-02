import pytest

from lib.infrastructure.ai_text_generation.json import (
    json_schema_response_format,
    parse_json_response,
    schema_prompt_block,
)


SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "properties": {"value": {"type": "string"}},
    "required": ["value"],
}


def test_parse_json_response_repairs_before_schema_validation():
    assert parse_json_response(
        'Result: ```json\n{"value":"ok"}\n```',
        SCHEMA,
    ) == {"value": "ok"}


def test_parse_json_response_reports_validation_path():
    with pytest.raises(ValueError, match=r"at \$\.value"):
        parse_json_response('{"value":7}', SCHEMA)


def test_json_schema_response_format_is_strict():
    result = json_schema_response_format(SCHEMA, name="test response")

    assert result["json_schema"]["name"] == "test_response"
    assert result["json_schema"]["strict"] is True
    assert result["json_schema"]["schema"] is SCHEMA


def test_schema_prompt_block_distinguishes_response_from_schema():
    prompt = schema_prompt_block(SCHEMA)

    assert prompt.startswith("### JSON OUTPUT\n")
    assert '"value": {' in prompt
    assert prompt.endswith(
        "Return the matching JSON object, not the schema."
    )
    assert "{{response_schema}}" not in prompt
