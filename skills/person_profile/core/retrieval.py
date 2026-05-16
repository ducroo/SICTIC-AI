from skills.dataset_chat.dataset_search import dataset_search
from lib.logger import get_logger

logger = get_logger(__name__)

async def get_filtered_chunks(dataset_name: str, name: str, query: str) -> list:
    """
    Retrieve chunks for a person from a dataset and apply progressive filtering 
    to prevent context overflow.
    """
    logger.info(f"Collating profile for '{name}' in dataset '{dataset_name}'...")
    
    chunks = await dataset_search(
        dataset_name=dataset_name,
        query=query,
        max_chunks=500,
        return_full_docs=True
    )
    
    if not chunks:
        return []

    # Filter chunks based on name words
    filter_words = [w.lower() for w in name.split() if w.strip()]
    
    # Stage 1: Content Filter
    content_filtered = []
    for chunk in chunks:
        if all(fw in chunk.text.lower() for fw in filter_words):
            content_filtered.append(chunk)

    def get_total_chars(chunk_list):
        return sum(len(c.text) for c in chunk_list)

    MAX_CHARS = 80000

    # Stage 2: Title Filter (if payload is too large)
    if get_total_chars(content_filtered) > MAX_CHARS:
        logger.info(f"Context too large ({get_total_chars(content_filtered)} chars). Applying title filter.")
        title_filtered = [c for c in content_filtered if any(fw in c.document_name.lower() for fw in filter_words)]
        if title_filtered:
            content_filtered = title_filtered
            
    return content_filtered
