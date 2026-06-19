"""Semantic search over an ingested dataset."""

from lib.datasets.embeddings import EmbeddingService
from lib.datasets.ingestion import sync_datasets
from lib.datasets.models import Chunk
from lib.adapters.qdrant import QdrantAdapter
from lib.logger import get_logger
from lib.slugify import slugify

logger = get_logger(__name__)


async def dataset_search(
    dataset_name: str,
    query: str | list[str] = "",
    max_chunks: int = 25,
) -> list[Chunk]:
    """Unified API to run semantic search and retrieve dataset chunks."""
    dataset_slug = slugify(dataset_name)
    await sync_datasets([dataset_slug], raise_on_error=True)
    queries = (
        [query.strip()]
        if isinstance(query, str) and query.strip()
        else [item.strip() for item in query if item.strip()]
        if not isinstance(query, str)
        else []
    )
    if not queries or max_chunks <= 0:
        return []

    try:
        embeddings = EmbeddingService()
        vectors = await embeddings.embed_many(queries)
        qdrant = QdrantAdapter(dataset_slug)
        result_lists = [
            qdrant.query(vector, limit=max_chunks)
            for vector in vectors
        ]
    except Exception as exc:
        logger.error("Semantic search failed: %s", exc)
        return []

    chunks = []
    seen_chunk_ids = set()
    for index in range(max_chunks):
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
            chunks.append(
                Chunk.model_validate(payload)
            )
            if len(chunks) >= max_chunks:
                return chunks
    return chunks
