from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_ollama_requests_always_include_computed_num_ctx(monkeypatch, mocker):
    from skills.llm_chat import llm_chat as module

    captured = {}

    async def fake_completion(kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
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

    result = await module.llm_chat("short prompt")

    assert result == "ok"
    assert captured["num_ctx"] == 4096
