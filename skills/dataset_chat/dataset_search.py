from skills.dataset_chat.core.models import Chunk
from skills.dataset_chat.core.ingestion import sync_datasets
from lib.adapters.qdrant import QdrantAdapter
from lib.slugify import slugify


async def dataset_search(
    dataset_name: str,
    query: str | list[str] = "",
    max_chunks: int = 25,
) -> list[Chunk]:
    """Unified API to run semantic search and retrieve dataset chunks."""
    dataset_slug = slugify(dataset_name)
    await sync_datasets([dataset_slug], raise_on_error=True)
    qdrant = QdrantAdapter(dataset_slug)
    return await qdrant.search(query, max_chunks=max_chunks)
