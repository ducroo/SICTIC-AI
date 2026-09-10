"""Optional cross-encoder reranking of retrieved chunks.

Dense and BM25 retrieval both score a query against a whole chunk in isolation.
A cross-encoder reads the query and the chunk together, which recovers accuracy
that a small local embedding model loses on long documents. Reranking is off
until RERANK_MODEL is configured, and any failure keeps the fusion order.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lib.datasets.models import Chunk
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
from lib.model_config import ModelEndpoint, rerank_endpoint

logger = get_logger(__name__)
_DEFAULT_REQUEST_TIMEOUT = 120.0


def _request_timeout() -> float:
    raw = get_env_var("RERANK_REQUEST_TIMEOUT", required=False)
    if raw is None:
        return _DEFAULT_REQUEST_TIMEOUT
    try:
        value = float(raw)
    except ValueError as error:
        raise InfrastructureError(
            "RERANK_REQUEST_TIMEOUT must be numeric",
            kind=InfrastructureErrorKind.CONFIGURATION,
            provider="reranking",
            operation="load_configuration",
        ) from error
    if value <= 0:
        raise InfrastructureError(
            "RERANK_REQUEST_TIMEOUT must be positive",
            kind=InfrastructureErrorKind.CONFIGURATION,
            provider="reranking",
            operation="load_configuration",
        )
    return value


def reranking_enabled() -> bool:
    return rerank_endpoint() is not None


def _ranked_indices(response) -> list[tuple[int, float | None]]:
    """Extract (index, score) pairs from a LiteLLM rerank response."""
    results = getattr(response, "results", None)
    if results is None and isinstance(response, dict):
        results = response.get("results")

    ranked: list[tuple[int, float | None]] = []
    for item in results or []:
        if isinstance(item, dict):
            index = item.get("index")
            score = item.get("relevance_score")
        else:
            index = getattr(item, "index", None)
            score = getattr(item, "relevance_score", None)
        if isinstance(index, int):
            ranked.append((index, score))
    return ranked


def _reorder(
    chunks: list[Chunk],
    ranked: list[tuple[int, float | None]],
) -> list[Chunk]:
    reordered: list[Chunk] = []
    seen: set[int] = set()
    for index, score in ranked:
        if not 0 <= index < len(chunks) or index in seen:
            continue
        seen.add(index)
        chunk = chunks[index]
        reordered.append(
            chunk.model_copy(update={"score": score})
            if score is not None
            else chunk
        )
    # Chunks the provider did not return keep their fusion order behind the
    # reranked ones, so reranking can never reduce recall.
    reordered.extend(
        chunk for index, chunk in enumerate(chunks) if index not in seen
    )
    return reordered


async def _request_rerank(
    endpoint: ModelEndpoint,
    query: str,
    documents: list[str],
) -> Any:
    return await scheduler.run(
        _execute_rerank,
        operation_kwargs={
            "endpoint": endpoint,
            "query": query,
            "documents": documents,
            "top_n": len(documents),
            "timeout": _request_timeout(),
        },
    )


async def _execute_rerank(
    *,
    endpoint: ModelEndpoint,
    query: str,
    documents: list[str],
    top_n: int,
    timeout: float,
) -> Any:
    import litellm

    litellm.disable_aiohttp_transport = True
    kwargs = endpoint.litellm_kwargs()
    kwargs.update(
        {
            "query": query,
            "documents": documents,
            "top_n": top_n,
            "timeout": timeout,
        }
    )
    return await litellm.arerank(**kwargs)


def _inspect_rerank(kwargs: Mapping[str, Any]) -> JobProfile:
    endpoint = kwargs["endpoint"]
    if not isinstance(endpoint, ModelEndpoint):
        raise TypeError("Reranking endpoint must be a ModelEndpoint")
    query = str(kwargs["query"])
    documents = kwargs["documents"]
    if not isinstance(documents, list) or not all(
        isinstance(document, str) for document in documents
    ):
        raise TypeError("Reranking documents must be a list of strings")
    return JobProfile(
        kind="reranking",
        descriptor=endpoint.model,
        input_size=len(query) + sum(len(document) for document in documents),
        parameters={
            "document_count": len(documents),
            "top_n": int(kwargs["top_n"]),
        },
    )


register_operation(_execute_rerank, _inspect_rerank)


async def rerank_chunks(query: str, chunks: list[Chunk]) -> list[Chunk]:
    """Reorder chunks by cross-encoder relevance when reranking is configured."""
    endpoint = rerank_endpoint()
    if endpoint is None or len(chunks) < 2 or not query.strip():
        return chunks

    try:
        response = await _request_rerank(
            endpoint,
            query,
            [chunk.text for chunk in chunks],
        )
    except Exception as exc:
        logger.warning(
            "Reranking with %s failed; keeping retrieval order: %s",
            endpoint.model,
            exc,
        )
        return chunks

    ranked = _ranked_indices(response)
    if not ranked:
        logger.warning(
            "Reranking with %s returned no usable results; "
            "keeping retrieval order.",
            endpoint.model,
        )
        return chunks

    logger.info("Reranked %s chunks with %s.", len(chunks), endpoint.model)
    return _reorder(chunks, ranked)
