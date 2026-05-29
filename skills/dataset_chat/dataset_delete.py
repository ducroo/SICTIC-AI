from typing import Optional
from lib.env import get_env_var
from lib.storage import get_storage
from lib.logger import get_logger
from lib.slugify import slugify
from qdrant_client import QdrantClient
from lib.adapters.qdrant import QdrantAdapter
from lib.storage_domains import dataset_parsed_path

logger = get_logger(__name__)

def dataset_delete(dataset: Optional[str] = None, embeddings: Optional[str] = None):
    if not dataset and not embeddings:
        raise ValueError("Must provide either a dataset or an embeddings target to delete.")

    client = QdrantClient(url=get_env_var("QDRANT_HOST"), timeout=60.0)
    all_collections = [col.name for col in client.get_collections().collections]
    storage = get_storage()

    # Scenario A: Delete specific dataset completely (all embeddings)
    if dataset and not embeddings:
        dataset_slug = slugify(dataset)
        parsed_base_path = dataset_parsed_path(dataset_slug)

        prefix = f"{dataset_slug}-"
        to_delete = [c for c in all_collections if c.startswith(prefix)]

        for col in to_delete:
            client.delete_collection(col)
            logger.info(f"[{dataset_slug}] Deleted Qdrant collection: {col}")

        if storage.exists(parsed_base_path):
            try:
                storage.rmtree(parsed_base_path)
                logger.info(f"[{dataset_slug}] Deleted cached parsed directory: {parsed_base_path}")
            except Exception as e:
                logger.error(f"[{dataset_slug}] Failed to delete cached parsed directory {parsed_base_path}: {e}")

        logger.info(f"[{dataset_slug}] Dataset fully deleted from parsed cache and Qdrant.")
        return

    # Scenario B: Delete specific embedding for a specific dataset
    if dataset and embeddings:
        dataset_slug = slugify(dataset)
        target_collection = QdrantAdapter.collection_for(dataset_slug, embeddings)
        
        if target_collection in all_collections:
            client.delete_collection(target_collection)
            logger.info(f"[{dataset_slug}] Deleted Qdrant collection: {target_collection}")
        else:
            logger.warning(f"[{dataset_slug}] Collection {target_collection} not found in Qdrant.")
            
        logger.info(f"[{dataset_slug}] Embedding '{embeddings}' deleted.")
        return

    # Scenario C: Delete a specific embedding across all datasets
    if not dataset and embeddings:
        suffix = f"-{slugify(embeddings)}"
        to_delete = [c for c in all_collections if c.endswith(suffix)]
        
        if not to_delete:
            logger.warning(f"No collections found ending with '{suffix}'.")
            return
            
        for col in to_delete:
            client.delete_collection(col)
            logger.info(f"Deleted Qdrant collection: {col}")
            
        logger.info(f"All embeddings matching '{embeddings}' deleted globally.")
        return
