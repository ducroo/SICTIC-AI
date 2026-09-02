from types import SimpleNamespace

import pytest

from lib.datasets import embeddings
from lib.datasets.embeddings import EmbeddingService


async def _run_now(operation, **_kwargs):
    return await operation(**_kwargs["operation_kwargs"])


@pytest.fixture(autouse=True)
def clear_vector_size_cache():
    embeddings._vector_size_cache.clear()


@pytest.mark.asyncio
async def test_embed_owns_provider_call_and_uses_scheduler(mocker):
    provider = mocker.patch(
        "litellm.aembedding",
        new=mocker.AsyncMock(
            return_value=SimpleNamespace(data=[{"embedding": [1.0, 2.0]}])
        ),
    )
    run = mocker.patch.object(
        embeddings.scheduler,
        "run",
        side_effect=_run_now,
    )

    assert await EmbeddingService().embed("abc") == [1.0, 2.0]

    request = provider.await_args.kwargs
    assert request["input"] == ["abc"]
    assert request["timeout"] == 300.0
    scheduled = run.await_args
    assert scheduled.args[0] is embeddings._execute_embedding
    profile = embeddings._inspect_embedding(
        scheduled.kwargs["operation_kwargs"]
    )
    assert profile.descriptor == "ollama/test-embedding:8b"
    assert profile.input_size == 3


@pytest.mark.asyncio
async def test_vector_size_probe_is_scheduled_and_cached(mocker):
    provider = mocker.patch(
        "litellm.aembedding",
        new=mocker.AsyncMock(
            return_value=SimpleNamespace(
                data=[{"embedding": [1.0, 2.0, 3.0]}]
            )
        ),
    )
    run = mocker.patch.object(
        embeddings.scheduler,
        "run",
        side_effect=_run_now,
    )
    service = EmbeddingService()

    assert await service.vector_size() == 3
    assert await service.vector_size() == 3

    provider.assert_awaited_once()
    assert run.await_count == 1
    profile = embeddings._inspect_embedding(
        run.await_args.kwargs["operation_kwargs"]
    )
    assert profile.input_size == len("test")
