"""Semantic search over an ingested dataset."""

from lib.datasets.embeddings import EmbeddingService
from lib.datasets.ingestion import sync_datasets
from lib.datasets.models import Chunk
from lib.datasets.reranking import rerank_chunks
from lib.datasets.retrieval import (
    apply_document_diversity,
    candidate_limit,
    max_chunks_per_document,
)
from lib.datasets.sparse import encode_query
from lib.adapters.qdrant import QdrantAdapter
from lib.logger import get_logger
from lib.slugify import slugify

logger = get_logger(__name__)


def _normalize_queries(query: str | list[str]) -> list[str]:
    if isinstance(query, str):
        stripped = query.strip()
        return [stripped] if stripped else []
    return [item.strip() for item in query if item.strip()]


def _retrieve(
    qdrant: QdrantAdapter,
    text: str,
    vector: list[float],
    *,
    limit: int,
    hybrid: bool,
) -> list:
    if hybrid:
        return qdrant.query_hybrid(vector, encode_query(text), limit=limit)
    return qdrant.query(vector, limit=limit)


def _merge_result_lists(result_lists: list, limit: int) -> list[Chunk]:
    """Interleave per-question results so every question keeps its best hits."""
    chunks: list[Chunk] = []
    seen_chunk_ids: set[str] = set()
    depth = max((len(results) for results in result_lists), default=0)
    for index in range(depth):
        for results in result_lists:
            if index >= len(results):
                continue
            result = results[index]
            chunk_id = str(result.id)
            if chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk_id)
            payload = dict(result.payload or {})
            payload["chunk_id"] = chunk_id
            payload["score"] = result.score
            chunks.append(Chunk.model_validate(payload))
            if len(chunks) >= limit:
                return chunks
    return chunks


async def dataset_search(
    dataset_name: str,
    query: str | list[str] = "",
    max_chunks: int = 25,
    raise_on_error: bool = False,
) -> list[Chunk]:
    """Unified API to run semantic search and retrieve dataset chunks.

    Retrieval runs wide, then narrows: dense and BM25 rankings are fused in
    Qdrant, an optional cross-encoder reranks the candidates, and a
    per-document cap keeps one large document from filling the whole result.
    """
    dataset_slug = slugify(dataset_name)
    await sync_datasets([dataset_slug], raise_on_error=True)
    queries = _normalize_queries(query)
    if not queries or max_chunks <= 0:
        return []

    candidates = candidate_limit(max_chunks)
    try:
        embeddings = EmbeddingService()
        vectors = await embeddings.embed_many(queries)
        qdrant = QdrantAdapter(dataset_slug)
        hybrid = qdrant.sparse_enabled()
        if not hybrid and qdrant.collection_exists():
            logger.info(
                "Collection %s has no BM25 vectors; using dense-only search. "
                "Run 'dataset_maintenance rebuild-index --dataset %s' to "
                "enable hybrid search.",
                qdrant.collection_name,
                dataset_slug,
            )
        result_lists = [
            _retrieve(qdrant, text, vector, limit=candidates, hybrid=hybrid)
            for text, vector in zip(queries, vectors)
        ]
    except Exception as exc:
        logger.exception("Semantic search failed for dataset '%s'.", dataset_slug)
        if raise_on_error:
            raise RuntimeError(
                f"Semantic search failed for dataset '{dataset_slug}': {exc}"
            ) from exc
        return []

    chunks = _merge_result_lists(result_lists, candidates)
    if not chunks:
        return []

    chunks = await rerank_chunks("\n\n".join(queries), chunks)
    return apply_document_diversity(
        chunks,
        max_chunks,
        max_chunks_per_document(max_chunks),
    )
