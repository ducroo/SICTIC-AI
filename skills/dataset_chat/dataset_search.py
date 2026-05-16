import os
from typing import Union, List
from skills.dataset_chat.core.models import Chunk
from skills.dataset_chat.core.ingestion import sync_datasets
from lib.adapters.qdrant import QdrantAdapter
from lib.env import get_env_var
from lib.logger import get_logger

logger = get_logger(__name__)

async def dataset_search(dataset_name: str, query: Union[str, List[str]] = "", max_chunks: int = None, threshold_factor: float = None, return_full_docs: bool = False) -> list:
    """Unified API to run search, merge, and deduplicate chunks."""
    dataset_name = dataset_name.lower()
    await sync_datasets([dataset_name])
    qdrant = QdrantAdapter(dataset_name)
    
    if max_chunks is None and threshold_factor is None:
        max_chunks = 25
        threshold_factor = 0.8

    if isinstance(query, str):
        q = query.strip()
        queries = [q] if q else []
    else:
        queries = query

    if not queries:
        return []

    fetch_limit = max_chunks * 10 if (return_full_docs and max_chunks) else (max_chunks if max_chunks else 1000)
    
    unique_chunks = {}
    for q in queries:
        # Pass threshold_factor=None to qdrant so we handle it globally here
        chunks = await qdrant.search(q, limit=fetch_limit, threshold_factor=None)
        for chunk in chunks:
            key = chunk.chunk_id
            if key not in unique_chunks or chunk.score > unique_chunks[key].score:
                unique_chunks[key] = chunk
                
    sorted_chunks = sorted(unique_chunks.values(), key=lambda x: x.score, reverse=True)
    
    if threshold_factor is not None and sorted_chunks:
        max_score = sorted_chunks[0].score
        threshold = max_score * threshold_factor
        sorted_chunks = [c for c in sorted_chunks if c.score >= threshold]

    if return_full_docs:
        unique_docs = {}
        parsed_base_path = os.path.join(get_env_var("GDRIVE_MOUNT"), "datasets_parsed", dataset_name)
        
        for chunk in sorted_chunks:
            doc_name = chunk.document_name
            if doc_name not in unique_docs:
                if max_chunks is not None and len(unique_docs) >= max_chunks:
                    break
                    
                parsed_filepath = os.path.join(parsed_base_path, doc_name + ".md")
                try:
                    with open(parsed_filepath, "r", encoding="utf-8") as f:
                        text = f.read()
                    
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

    if max_chunks is not None:
        return sorted_chunks[:max_chunks]
    return sorted_chunks
