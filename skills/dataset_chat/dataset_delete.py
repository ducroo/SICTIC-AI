import os
import shutil
from typing import Optional
from skills.utils.env import get_env_var
from skills.utils.logger import get_logger
from skills.utils.slugify import slugify
from qdrant_client import QdrantClient

logger = get_logger(__name__)

def dataset_delete(dataset: Optional[str] = None, embeddings: Optional[str] = None):
    if not dataset and not embeddings:
        raise ValueError("Must provide either a dataset or an embeddings target to delete.")
        
    client = QdrantClient(url=get_env_var("QDRANT_HOST"), timeout=60.0)
    all_collections = [col.name for col in client.get_collections().collections]
    
    gdrive_mount = get_env_var("GDRIVE_MOUNT")
    
    # Scenario A: Delete specific dataset completely (all embeddings)
    if dataset and not embeddings:
        dataset = dataset.lower()
        parsed_base_path = os.path.join(gdrive_mount, "datasets_parsed", dataset)
        
        prefix = f"{dataset}_"
        to_delete = [c for c in all_collections if c.startswith(prefix)]
        
        for col in to_delete:
            client.delete_collection(col)
            logger.info(f"[{dataset}] Deleted Qdrant collection: {col}")
            
        if os.path.exists(parsed_base_path):
            try:
                shutil.rmtree(parsed_base_path)
                logger.info(f"[{dataset}] Deleted cached parsed directory: {parsed_base_path}")
            except Exception as e:
                logger.error(f"[{dataset}] Failed to delete cached parsed directory {parsed_base_path}: {e}")
                
        logger.info(f"[{dataset}] Dataset fully deleted from parsed cache and Qdrant.")
        return

    # Scenario B: Delete specific embedding for a specific dataset
    if dataset and embeddings:
        dataset = dataset.lower()
        target_collection = f"{dataset}_{slugify(embeddings)}"
        
        if target_collection in all_collections:
            client.delete_collection(target_collection)
            logger.info(f"[{dataset}] Deleted Qdrant collection: {target_collection}")
        else:
            logger.warning(f"[{dataset}] Collection {target_collection} not found in Qdrant.")
            
        logger.info(f"[{dataset}] Embedding '{embeddings}' deleted.")
        return

    # Scenario C: Delete a specific embedding across all datasets
    if not dataset and embeddings:
        suffix = f"_{slugify(embeddings)}"
        to_delete = [c for c in all_collections if c.endswith(suffix)]
        
        if not to_delete:
            logger.warning(f"No collections found ending with '{suffix}'.")
            return
            
        for col in to_delete:
            client.delete_collection(col)
            logger.info(f"Deleted Qdrant collection: {col}")
            
        logger.info(f"All embeddings matching '{embeddings}' deleted globally.")
        return
