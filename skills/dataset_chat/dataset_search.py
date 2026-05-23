from typing import Union, List
from skills.dataset_chat.core.models import Chunk
from skills.dataset_chat.core.ingestion import sync_datasets
from lib.adapters.qdrant import QdrantAdapter
from lib.storage import get_storage
from lib.logger import get_logger

logger = get_logger(__name__)

async def dataset_search(dataset_name: str, query: Union[str, List[str]] = "", max_chunks: int = None, threshold_factor: float = None, return_full_docs: bool = False) -> list:
    """Unified API to run search and retrieve chunks or full documents."""
    dataset_name = dataset_name.lower()
    await sync_datasets([dataset_name])
    qdrant = QdrantAdapter(dataset_name)
    
    if max_chunks is None and threshold_factor is None:
        max_chunks = 25
        threshold_factor = 0.8

    # When returning full documents, we need to fetch more chunks internally 
    # to guarantee we hit enough unique source documents.
    fetch_limit = max_chunks * 10 if (return_full_docs and max_chunks) else (max_chunks if max_chunks else 1000)
    
    sorted_chunks = await qdrant.search(query, limit=fetch_limit, threshold_factor=threshold_factor)

    if return_full_docs:
        unique_docs = {}
        storage = get_storage()
        parsed_base_path = f"dataset2md/{dataset_name}"

        for chunk in sorted_chunks:
            doc_name = chunk.document_name
            if doc_name not in unique_docs:
                if max_chunks is not None and len(unique_docs) >= max_chunks:
                    break

                parsed_filepath = f"{parsed_base_path}/{doc_name}.md"
                try:
                    text = storage.read_text(parsed_filepath)

                    # Store as a full-document Chunk
                    unique_docs[doc_name] = Chunk(
                        chunk_id=doc_name,
                        document_name=doc_name,
                        page_number="all",
                        last_modified=chunk.last_modified,
                        text=text,
                        score=chunk.score
                    )
                except Exception as e:
                    logger.error(f"[{dataset_name}] Failed to load full document {parsed_filepath}: {e}")
                    unique_docs[doc_name] = chunk

        return list(unique_docs.values())

    return sorted_chunks
