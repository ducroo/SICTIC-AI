"""Optional cross-encoder reranking of retrieved chunks.

Dense and BM25 retrieval both score a query against a whole chunk in isolation.
A cross-encoder reads the query and the chunk together, which recovers accuracy
that a small local embedding model loses on long documents. Reranking is off
until RERANK_MODEL is configured, and any failure keeps the fusion order.
"""

from __future__ import annotations

from lib.datasets.models import Chunk
from lib.logger import get_logger
from lib.model_config import rerank_endpoint
from lib.services_gateway import gateway

logger = get_logger(__name__)


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


def _reorder(chunks: list[Chunk], ranked: list[tuple[int, float | None]]) -> list[Chunk]:
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


async def rerank_chunks(query: str, chunks: list[Chunk]) -> list[Chunk]:
    """Reorder chunks by cross-encoder relevance when reranking is configured."""
    endpoint = rerank_endpoint()
    if endpoint is None or len(chunks) < 2 or not query.strip():
        return chunks

    kwargs = endpoint.litellm_kwargs()
    kwargs["query"] = query
    kwargs["documents"] = [chunk.text for chunk in chunks]
    kwargs["top_n"] = len(chunks)
    try:
        response = await gateway.request_rerank(kwargs)
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
