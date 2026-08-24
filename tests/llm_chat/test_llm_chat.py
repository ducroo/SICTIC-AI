from __future__ import annotations

from types import SimpleNamespace
import hashlib

import pytest


@pytest.mark.asyncio
async def test_ollama_requests_always_include_computed_num_ctx(monkeypatch, mocker):
    from skills.llm_chat import llm_chat as module

    captured = {}
    usage = {
        "prompt_tokens": 1200,
        "prompt_tokens_details": {"cached_tokens": 1024},
        "completion_tokens": 24,
    }

    async def fake_completion(kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            usage=usage,
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="ok"),
                )
            ]
        )

    monkeypatch.setenv("LLM_MODEL", "ollama/example")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH", "4096")
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH_MAX", "8192")
    mocker.patch.object(module.gateway, "request_completion", side_effect=fake_completion)
    log_info = mocker.patch.object(module.logger, "info")

    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "fixture",
            "strict": True,
            "schema": {"type": "object"},
        },
    }
    result = await module.llm_chat(
        "short prompt",
        response_format=response_format,
    )

    assert result == "ok"
    assert captured["num_ctx"] == 4096
    assert captured["response_format"] == response_format
    log_info.assert_any_call("LLM usage for %s: %s", "ollama/example", usage)


@pytest.mark.asyncio
async def test_gpt56_explicit_cache_request_preserves_prefix_boundary(
    monkeypatch,
    mocker,
):
    from skills.llm_chat import llm_chat as module

    captured = {}

    async def fake_completion(kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            usage={"prompt_tokens": 10},
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
        )

    monkeypatch.setenv("LLM_MODEL", "openai/gpt-5.6-luna")
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH", "4096")
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH_MAX", "8192")
    mocker.patch.object(module.gateway, "request_completion", side_effect=fake_completion)

    prefix = "stable instructions and documents\n\n"
    result = await module.llm_chat(
        "dynamic question and retrieval context",
        cacheable_prompt_prefix=prefix,
    )

    assert result == "ok"
    assert captured["messages"] == [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": prefix,
                    "prompt_cache_breakpoint": {"mode": "explicit"},
                },
                {
                    "type": "text",
                    "text": "dynamic question and retrieval context",
                },
            ],
        }
    ]
    digest = hashlib.sha256(prefix.encode("utf-8")).hexdigest()[:32]
    assert captured["extra_body"] == {
        "prompt_cache_key": f"sictic-ai:{digest}",
        "prompt_cache_options": {"mode": "explicit"},
    }


@pytest.mark.asyncio
async def test_ollama_does_not_receive_openai_cache_parameters(monkeypatch, mocker):
    from skills.llm_chat import llm_chat as module

    captured = {}

    async def fake_completion(kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            usage=None,
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
        )

    monkeypatch.setenv("LLM_MODEL", "ollama/example")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH", "4096")
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH_MAX", "8192")
    mocker.patch.object(module.gateway, "request_completion", side_effect=fake_completion)

    await module.llm_chat(
        "dynamic question",
        cacheable_prompt_prefix="stable prefix\n\n",
    )

    assert captured["messages"] == [
        {"role": "user", "content": "stable prefix\n\ndynamic question"}
    ]
    assert "extra_body" not in captured
