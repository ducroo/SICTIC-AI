from typing import Union, List
from skills.dataset_chat.core.models import Chunk
from skills.dataset_chat.core.ingestion import sync_datasets
from lib.adapters.qdrant import QdrantAdapter
from lib.storage import get_storage
from lib.logger import get_logger

logger = get_logger(__name__)

async def dataset_search(dataset_name: str, query: Union[str, List[str]] = "", max_chunks: int = None, threshold_factor: float = None) -> list[Chunk]:
    """Unified API to run semantic search and retrieve dataset chunks."""
    from lib.slugify import slugify
    dataset_slug = slugify(dataset_name)
    await sync_datasets([dataset_slug], raise_on_error=True)
    qdrant = QdrantAdapter(dataset_slug)
    
    if max_chunks is None and threshold_factor is None:
        max_chunks = 25
        threshold_factor = 0.8
        
    sorted_chunks = await qdrant.search(query, limit=max_chunks, threshold_factor=threshold_factor)
    return sorted_chunks
