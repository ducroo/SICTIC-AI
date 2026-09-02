"""Embedding operations used by dataset search and ingestion."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from lib.infrastructure.configuration import get_env_var
from lib.infrastructure.errors import (
    InfrastructureError,
    InfrastructureErrorKind,
)
from lib.infrastructure.logging import get_logger
from lib.infrastructure.scheduler import scheduler
from lib.infrastructure.scheduler_operations import (
    JobProfile,
    register_operation,
)
from lib.model_config import ModelEndpoint, embedding_endpoint, embedding_model

logger = get_logger(__name__)

_vector_size_cache: dict[tuple[str, str], int] = {}
_DEFAULT_REQUEST_TIMEOUT = 300.0


def _request_timeout() -> float:
    raw = get_env_var("EMBEDDING_REQUEST_TIMEOUT", required=False)
    if raw is None:
        return _DEFAULT_REQUEST_TIMEOUT
    try:
        value = float(raw)
    except ValueError as error:
        raise InfrastructureError(
            "EMBEDDING_REQUEST_TIMEOUT must be numeric",
            kind=InfrastructureErrorKind.CONFIGURATION,
            provider="embedding",
            operation="load_configuration",
        ) from error
    if value <= 0:
        raise InfrastructureError(
            "EMBEDDING_REQUEST_TIMEOUT must be positive",
            kind=InfrastructureErrorKind.CONFIGURATION,
            provider="embedding",
            operation="load_configuration",
        )
    return value


class EmbeddingService:
    def __init__(self):
        self.model = embedding_model()
        self.endpoint = embedding_endpoint()

    async def vector_size(self) -> int:
        kwargs = self.endpoint.litellm_kwargs()
        cache_key = (self.model, repr(sorted(kwargs.items())))
        cached_size = _vector_size_cache.get(cache_key)
        if cached_size is not None:
            return cached_size
        try:
            response = await self._request(["test"])
            size = len(response.data[0]["embedding"])
            _vector_size_cache[cache_key] = size
            logger.info(
                "Dynamically determined vector size: %s for model %s",
                size,
                self.model,
            )
            return size
        except Exception as exc:
            logger.error("Failed to determine vector size dynamically: %s", exc)
            raise RuntimeError(
                f"Could not determine embedding vector size for {self.model}: {exc}"
            ) from exc

    async def embed(self, text: str) -> list[float]:
        try:
            response = await self._request([text])
            return response.data[0]["embedding"]
        except Exception as exc:
            logger.error("Failed to generate embedding: %s", exc)
            raise RuntimeError(f"Embedding failed: {exc}") from exc

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.gather(*(self.embed(text) for text in texts))

    async def _request(self, texts: list[str]) -> Any:
        return await scheduler.run(
            _execute_embedding,
            operation_kwargs={
                "endpoint": self.endpoint,
                "texts": texts,
                "timeout": _request_timeout(),
            },
        )


async def _execute_embedding(
    *,
    endpoint: ModelEndpoint,
    texts: list[str],
    timeout: float,
) -> Any:
    import litellm

    litellm.disable_aiohttp_transport = True
    kwargs = endpoint.litellm_kwargs()
    kwargs.update({"input": texts, "timeout": timeout})
    return await litellm.aembedding(**kwargs)


def _inspect_embedding(kwargs: Mapping[str, Any]) -> JobProfile:
    endpoint = kwargs["endpoint"]
    if not isinstance(endpoint, ModelEndpoint):
        raise TypeError("Embedding endpoint must be a ModelEndpoint")
    texts = kwargs["texts"]
    if not isinstance(texts, list) or not all(
        isinstance(text, str) for text in texts
    ):
        raise TypeError("Embedding texts must be a list of strings")
    return JobProfile(
        kind="embedding",
        descriptor=endpoint.model,
        input_size=sum(len(text) for text in texts),
        parameters={"text_count": len(texts)},
    )


register_operation(_execute_embedding, _inspect_embedding)
