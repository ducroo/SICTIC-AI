from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from lib.infrastructure.ai_text_generation import (
    Review,
    generate_json,
    generate_markdown,
)
from lib.infrastructure.ai_text_generation import generation
from lib.infrastructure.ai_text_generation import measurements
from lib.infrastructure.errors import (
    InfrastructureError,
    InfrastructureErrorKind,
)


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["ids"],
}


async def _run_now(operation, **_kwargs):
    return await operation(**_kwargs["operation_kwargs"])


def _response(content: str, usage=None):
    return SimpleNamespace(
        usage=usage,
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
    )


@pytest.fixture(autouse=True)
def immediate_scheduler(mocker):
    mocker.patch.object(
        generation.scheduler,
        "run",
        side_effect=_run_now,
    )


@pytest.mark.asyncio
async def test_generate_markdown_uses_dynamic_ollama_context(
    monkeypatch,
    mocker,
):
    monkeypatch.setenv("LLM_MODEL", "ollama/example")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH", "4096")
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH_MAX", "8192")
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT", "1200")
    completion = mocker.patch.object(
        generation,
        "_completion",
        return_value=_response("  # Result\n"),
    )
    prefix = "Shared instructions\n\n"

    result = await generate_markdown(
        "short prompt",
        cacheable_prompt_prefix=prefix,
    )

    assert result == "# Result"
    request = completion.await_args.args[0]
    assert request["num_ctx"] == 4096
    assert request["timeout"] == 1200.0
    scheduled = generation.scheduler.run.await_args
    profile = generation._inspect_text_request(
        scheduled.kwargs["operation_kwargs"]
    )
    digest = hashlib.sha256(prefix.encode()).hexdigest()[:32]
    assert profile.affinity_key == f"sictic-ai:{digest}"


@pytest.mark.asyncio
async def test_generate_markdown_does_not_truncate_oversized_prompt(
    monkeypatch,
    mocker,
):
    monkeypatch.setenv("LLM_MODEL", "ollama/example")
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH", "4")
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH_MAX", "8")
    completion = mocker.patch.object(generation, "_completion")

    with pytest.raises(InfrastructureError) as raised:
        await generate_markdown("x" * 30)

    assert raised.value.kind is InfrastructureErrorKind.DATA_INTEGRITY
    assert "was not truncated" in str(raised.value)
    completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_markdown_retries_reviewer_rejection(mocker, caplog):
    completion = mocker.patch.object(
        generation,
        "_completion",
        side_effect=[
            _response("Too vague"),
            _response("Specific answer"),
        ],
    )

    def reviewer(output: str) -> Review[str]:
        if output == "Too vague":
            return Review(output, ("Include the actual result",))
        return Review(output)

    result = await generate_markdown("Explain", reviewer)

    assert result == "Specific answer"
    assert (
        "Markdown generation attempt 1/3 failed; retrying: "
        "Include the actual result"
    ) in caplog.text
    retry_prompt = completion.await_args_list[1].args[0]["messages"][0][
        "content"
    ]
    assert "Include the actual result" in retry_prompt


@pytest.mark.asyncio
async def test_generate_json_passes_schema_and_repairs_output(mocker):
    completion = mocker.patch.object(
        generation,
        "_completion",
        return_value=_response('```json\n{"ids":["a"],}\n```'),
    )

    result = await generate_json("Rank the IDs", SCHEMA)

    assert result == {"ids": ["a"]}
    request = completion.await_args.args[0]
    response_format = request["response_format"]
    assert response_format["json_schema"]["schema"] is SCHEMA
    assert "Return the matching JSON object" in request["messages"][0][
        "content"
    ]
    assert request["think"] is True


@pytest.mark.asyncio
async def test_generate_json_revalidates_reviewer_corrections(mocker):
    completion = mocker.patch.object(
        generation,
        "_completion",
        return_value=_response('{"ids":["a","a"]}'),
    )

    def reviewer(output: dict | list) -> Review[dict | list]:
        assert isinstance(output, dict)
        return Review({"ids": list(dict.fromkeys(output["ids"]))})

    result = await generate_json("Rank", SCHEMA, reviewer)

    assert result == {"ids": ["a"]}
    assert completion.await_count == 1


@pytest.mark.asyncio
async def test_generate_json_retries_with_schema_feedback(mocker, caplog):
    completion = mocker.patch.object(
        generation,
        "_completion",
        side_effect=[
            _response('{"ids":"a"}'),
            _response('{"reasoning":"Check the type","ids":["a"]}'),
        ],
    )

    result = await generate_json("Rank", SCHEMA)

    assert result == {"ids": ["a"]}
    assert "JSON generation attempt 1/2 failed; retrying:" in caplog.text
    assert "does not match the schema" in caplog.text
    retry_prompt = completion.await_args_list[1].args[0]["messages"][0][
        "content"
    ]
    assert "does not match the schema" in retry_prompt
    retry_request = completion.await_args_list[1].args[0]
    retry_schema = retry_request["response_format"]["json_schema"]["schema"]
    assert next(iter(retry_schema["properties"])) == "reasoning"
    assert retry_schema["required"][0] == "reasoning"
    assert retry_request["think"] is False
    assert SCHEMA["properties"] == {
        "ids": {"type": "array", "items": {"type": "string"}}
    }


@pytest.mark.asyncio
async def test_generate_json_retries_provider_schema_rejection(mocker):
    from litellm.exceptions import JSONSchemaValidationError

    completion = mocker.patch.object(
        generation,
        "_completion",
        side_effect=[
            JSONSchemaValidationError(
                model="fixture",
                llm_provider="fixture",
                raw_response='{"ids":"a"}',
                schema=json.dumps(SCHEMA),
            ),
            _response('{"reasoning":"Correct the type","ids":["a"]}'),
        ],
    )

    assert await generate_json("Rank", SCHEMA) == {"ids": ["a"]}
    assert completion.await_count == 2


@pytest.mark.asyncio
async def test_generate_json_stops_after_two_attempts(mocker):
    completion = mocker.patch.object(
        generation,
        "_completion",
        return_value=_response('{"ids":"a"}'),
    )

    with pytest.raises(InfrastructureError, match="after 2 attempts"):
        await generate_json("Rank", SCHEMA)

    assert completion.await_count == 2


@pytest.mark.asyncio
async def test_generate_json_strips_reasoning_before_review(mocker):
    completion = mocker.patch.object(
        generation,
        "_completion",
        side_effect=[
            _response('{"ids":"a"}'),
            _response(
                '{"reasoning":"Remove duplicates","ids":["a","a"]}'
            ),
        ],
    )

    def reviewer(output: dict | list) -> Review[dict | list]:
        assert output == {"ids": ["a", "a"]}
        return Review({"ids": ["a"]})

    assert await generate_json("Rank", SCHEMA, reviewer) == {"ids": ["a"]}


@pytest.mark.asyncio
async def test_generate_json_wraps_array_schema_on_fallback(mocker):
    schema = {"type": "array", "items": {"type": "string"}}
    completion = mocker.patch.object(
        generation,
        "_completion",
        side_effect=[
            _response("not JSON"),
            _response('{"reasoning":"Collect values","result":["a"]}'),
        ],
    )

    assert await generate_json("Collect", schema) == ["a"]
    retry = completion.await_args_list[1].args[0]
    retry_schema = retry["response_format"]["json_schema"]["schema"]
    assert list(retry_schema["properties"]) == ["reasoning", "result"]


@pytest.mark.asyncio
async def test_generate_json_places_schema_after_stable_prefix(
    monkeypatch,
    mocker,
):
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-5.6-luna")
    completion = mocker.patch.object(
        generation,
        "_completion",
        return_value=_response(json.dumps({"ids": ["a"]})),
    )
    prefix = "Shared instructions\n\n"

    await generate_json(
        "Current item",
        SCHEMA,
        cacheable_prompt_prefix=prefix,
    )

    request = completion.await_args.args[0]
    content = request["messages"][0]["content"]
    assert content[0]["text"] == prefix
    assert "Return the matching JSON object" not in content[0]["text"]
    assert content[1]["text"].startswith("### JSON OUTPUT")
    assert "Return the matching JSON object" in content[1]["text"]
    assert content[1]["text"].endswith("Current item")
    digest = hashlib.sha256(content[0]["text"].encode()).hexdigest()[:32]
    assert request["extra_body"]["prompt_cache_key"] == (
        f"sictic-ai:{digest}"
    )
    scheduled = generation.scheduler.run.await_args
    profile = generation._inspect_text_request(
        scheduled.kwargs["operation_kwargs"]
    )
    assert profile.affinity_key == f"sictic-ai:{digest}"


@pytest.mark.asyncio
async def test_generation_measurement_is_privacy_safe_jsonl(
    tmp_path,
    monkeypatch,
    mocker,
):
    monkeypatch.delenv("SICTIC_TESTING")
    measurement_file = tmp_path / "logs" / "ai-text-generation.jsonl"
    monkeypatch.setattr(
        measurements,
        "MEASUREMENT_FILE",
        measurement_file,
    )
    mocker.patch.object(
        generation.scheduler,
        "snapshot",
        return_value={
            "leases": {
                "docling": [],
                "model": [{"descriptor": "ollama/example"}],
            }
        },
    )
    completion = mocker.patch.object(
        generation,
        "_completion",
        return_value=_response(
            "private generated text",
            usage={
                "prompt_tokens": 11,
                "completion_tokens": 3,
                "prompt_tokens_details": {"cached_tokens": 2},
                "completion_tokens_details": {"reasoning_tokens": 1},
            },
        ),
    )

    await generate_markdown("private prompt text")

    [record] = [
        json.loads(line)
        for line in measurement_file.read_text(encoding="utf-8").splitlines()
    ]
    assert record["schema_version"] == 2
    assert record["output_type"] == "markdown"
    assert record["attempt"] == 1
    assert record["input_characters"] == len("private prompt text")
    assert record["output_characters"] == len("private generated text")
    assert record["prompt_tokens"] == 11
    assert record["completion_tokens"] == 3
    assert record["cached_prompt_tokens"] == 2
    assert record["reasoning_tokens"] == 1
    assert record["concurrent_local_jobs"] == 1
    assert record["thinking_enabled"] is None
    serialized = json.dumps(record)
    assert "private prompt text" not in serialized
    assert "private generated text" not in serialized
    completion.assert_awaited_once()
