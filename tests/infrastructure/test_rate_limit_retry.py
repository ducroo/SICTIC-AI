"""Tests for the rate-limit wait-and-retry helper and its call sites."""

from __future__ import annotations

import pytest

from lib.infrastructure.errors import (
    InfrastructureError,
    InfrastructureErrorKind,
)
from lib.infrastructure.logging import get_logger
from lib.infrastructure.retry import with_rate_limit_retry

logger = get_logger(__name__)


class _RateLimit(Exception):
    pass


def _is_rate_limit(error: BaseException) -> bool:
    return isinstance(error, _RateLimit)


def _no_sleep(monkeypatch, waits: list[float]) -> None:
    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr("lib.infrastructure.retry.asyncio.sleep", fake_sleep)


@pytest.mark.asyncio
async def test_success_needs_no_retry(monkeypatch) -> None:
    waits: list[float] = []
    _no_sleep(monkeypatch, waits)
    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        return "ok"

    result = await with_rate_limit_retry(
        operation, is_rate_limit=_is_rate_limit, logger=logger, label="t"
    )
    assert result == "ok"
    assert calls == 1
    assert waits == []


@pytest.mark.asyncio
async def test_waits_out_rate_limits_then_succeeds(monkeypatch) -> None:
    waits: list[float] = []
    _no_sleep(monkeypatch, waits)
    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise _RateLimit("429")
        return "ok"

    result = await with_rate_limit_retry(
        operation,
        is_rate_limit=_is_rate_limit,
        logger=logger,
        label="t",
        delays=(10.0, 20.0, 40.0),
    )
    assert result == "ok"
    assert calls == 3
    assert len(waits) == 2
    # Jitter is upward only: each wait is at least its base delay.
    assert waits[0] >= 10.0 and waits[1] >= 20.0
    assert waits[0] <= 12.5 and waits[1] <= 25.0


@pytest.mark.asyncio
async def test_other_errors_propagate_without_waiting(monkeypatch) -> None:
    waits: list[float] = []
    _no_sleep(monkeypatch, waits)

    async def operation() -> str:
        raise ValueError("not a rate limit")

    with pytest.raises(ValueError):
        await with_rate_limit_retry(
            operation, is_rate_limit=_is_rate_limit, logger=logger, label="t"
        )
    assert waits == []


@pytest.mark.asyncio
async def test_exhausted_delays_raise_the_rate_limit(monkeypatch) -> None:
    waits: list[float] = []
    _no_sleep(monkeypatch, waits)
    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        raise _RateLimit("429")

    with pytest.raises(_RateLimit):
        await with_rate_limit_retry(
            operation,
            is_rate_limit=_is_rate_limit,
            logger=logger,
            label="t",
            delays=(1.0, 2.0),
        )
    assert calls == 3  # one try per delay plus the final one
    assert len(waits) == 2


@pytest.mark.asyncio
async def test_generate_json_does_not_burn_attempts_on_429(
    monkeypatch, mock_env
) -> None:
    """A throttled call retries within ONE generation attempt."""
    from lib.infrastructure.ai_text_generation import generation

    waits: list[float] = []
    _no_sleep(monkeypatch, waits)
    attempts_seen: list[int] = []
    calls = 0

    async def fake_request_text(*, prompt, attempt, **_kwargs) -> str:
        nonlocal calls
        calls += 1
        attempts_seen.append(attempt)
        if calls <= 2:
            raise InfrastructureError(
                "429",
                kind=InfrastructureErrorKind.RATE_LIMIT,
                provider="gemini/test",
                operation="generate_text",
            )
        return '{"value": 1}'

    monkeypatch.setattr(generation, "_request_text", fake_request_text)
    schema = {
        "type": "object",
        "properties": {"value": {"type": "integer"}},
        "required": ["value"],
        "additionalProperties": False,
    }
    result = await generation.generate_json("prompt", schema)
    assert result == {"value": 1}
    # Two 429s were absorbed by waiting, all within generation attempt 1.
    assert attempts_seen == [1, 1, 1]
    assert len(waits) == 2


@pytest.mark.asyncio
async def test_embedding_request_retries_rate_limits(monkeypatch) -> None:
    from litellm.exceptions import RateLimitError

    from lib.datasets import embeddings as embeddings_module

    waits: list[float] = []
    _no_sleep(monkeypatch, waits)
    calls = 0

    async def fake_scheduler_run(operation, operation_kwargs) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RateLimitError(
                message="429", model="test", llm_provider="gemini"
            )

        class _Response:
            data = [{"embedding": [0.0, 1.0]}]

        return _Response()

    monkeypatch.setattr(
        embeddings_module.scheduler, "run", fake_scheduler_run
    )
    service = embeddings_module.EmbeddingService.__new__(
        embeddings_module.EmbeddingService
    )
    service.model = "gemini/test-embedding"
    service.endpoint = None
    monkeypatch.setattr(
        embeddings_module, "_request_timeout", lambda: 1.0
    )
    result = await service.embed("hello")
    assert result == [0.0, 1.0]
    assert calls == 2
    assert len(waits) == 1


@pytest.mark.asyncio
async def test_generation_also_waits_out_503_overload(
    monkeypatch, mock_env
) -> None:
    """Gemini 'high demand' 503s are as transient as 429s."""
    from lib.infrastructure.ai_text_generation import generation

    waits: list[float] = []
    _no_sleep(monkeypatch, waits)
    calls = 0

    async def fake_request_text(*, prompt, attempt, **_kwargs) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise InfrastructureError(
                "503 high demand",
                kind=InfrastructureErrorKind.SERVICE_UNAVAILABLE,
                provider="gemini/test",
                operation="generate_text",
            )
        return '{"value": 2}'

    monkeypatch.setattr(generation, "_request_text", fake_request_text)
    schema = {
        "type": "object",
        "properties": {"value": {"type": "integer"}},
        "required": ["value"],
        "additionalProperties": False,
    }
    result = await generation.generate_json("prompt", schema)
    assert result == {"value": 2}
    assert len(waits) == 1


@pytest.mark.asyncio
async def test_embedding_retries_service_unavailable(monkeypatch) -> None:
    from litellm.exceptions import ServiceUnavailableError

    from lib.datasets import embeddings as embeddings_module

    waits: list[float] = []
    _no_sleep(monkeypatch, waits)
    calls = 0

    async def fake_scheduler_run(operation, operation_kwargs) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ServiceUnavailableError(
                message="503", model="test", llm_provider="gemini"
            )

        class _Response:
            data = [{"embedding": [1.0]}]

        return _Response()

    monkeypatch.setattr(
        embeddings_module.scheduler, "run", fake_scheduler_run
    )
    service = embeddings_module.EmbeddingService.__new__(
        embeddings_module.EmbeddingService
    )
    service.model = "gemini/test-embedding"
    service.endpoint = None
    monkeypatch.setattr(
        embeddings_module, "_request_timeout", lambda: 1.0
    )
    assert await service.embed("x") == [1.0]
    assert calls == 2
