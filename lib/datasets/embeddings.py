"""Embedding operations used by dataset search and ingestion."""

from __future__ import annotations

import asyncio

from lib.logger import get_logger
from lib.model_config import embedding_endpoint, embedding_model
from lib.services_gateway import gateway

logger = get_logger(__name__)

_vector_size_cache: dict[tuple[str, str], int] = {}


class EmbeddingService:
    def __init__(self):
        self.model = embedding_model()
        self.endpoint = embedding_endpoint()

    def vector_size(self) -> int:
        import litellm

        kwargs = self.endpoint.litellm_kwargs()
        cache_key = (self.model, repr(sorted(kwargs.items())))
        cached_size = _vector_size_cache.get(cache_key)
        if cached_size is not None:
            return cached_size
        kwargs["model"] = self.model
        kwargs["input"] = ["test"]
        try:
            response = litellm.embedding(**kwargs)
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
        kwargs = self.endpoint.litellm_kwargs()
        kwargs["input"] = [text]
        try:
            response = await gateway.request_embedding(kwargs)
            return response.data[0]["embedding"]
        except Exception as exc:
            logger.error("Failed to generate embedding: %s", exc)
            raise RuntimeError(f"Embedding failed: {exc}") from exc

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.gather(*(self.embed(text) for text in texts))
