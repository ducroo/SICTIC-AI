import os
import shutil
from typing import List
from skills.dataset_chat.core.ingestion import sync_datasets
from skills.utils.adapters.qdrant import QdrantAdapter
from skills.utils.env import get_env_var
from skills.utils.logger import get_logger

logger = get_logger(__name__)

def prepare_ephemeral_dataset(files: List[str], temp_name: str = "temp") -> str:
    """
    1. Cleans up any existing ephemeral dataset from previous runs.
    2. Sets up a temporary dataset directory.
    3. Copies the provided files into it.
    4. Runs the ingestion pipeline to parse and embed them.
    5. Returns the dataset name (e.g., 'temp') for the skill to use.
    """
    gdrive_mount = get_env_var("GDRIVE_MOUNT")
    raw_dataset_path = os.path.join(gdrive_mount, "datasets", temp_name)
    parsed_dataset_path = os.path.join(gdrive_mount, "datasets_parsed", temp_name)
    
    # 1. Cleanup previous run
    logger.info(f"Cleaning up previous ephemeral dataset '{temp_name}'...")
    if os.path.exists(raw_dataset_path):
        shutil.rmtree(raw_dataset_path, ignore_errors=True)
    if os.path.exists(parsed_dataset_path):
        shutil.rmtree(parsed_dataset_path, ignore_errors=True)
    try:
        qdrant = QdrantAdapter(temp_name)
        qdrant.delete_collection()
    except Exception as e:
        logger.debug(f"Could not delete collection during cleanup (might not exist): {e}")
        
    # 2. Setup: Create directories and copy files
    os.makedirs(raw_dataset_path, exist_ok=True)
    for file_path in files:
        if os.path.exists(file_path):
            shutil.copy(file_path, raw_dataset_path)
        else:
            logger.warning(f"Provided file does not exist: {file_path}")
            
    # 3. Ingest: Parse to markdown and embed in Qdrant
    logger.info(f"Ingesting ephemeral dataset '{temp_name}'...")
    sync_datasets([temp_name])
    
    return temp_name
