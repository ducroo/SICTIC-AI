import os
from typing import List

from lib.datasets.ingestion import sync_datasets
from lib.infrastructure.qdrant import QdrantAdapter
from lib.infrastructure.logging import get_logger
from lib.storage import get_storage
from lib.datasets.paths import dataset_location_for_domain

logger = get_logger(__name__)


async def discard_ephemeral_dataset(temp_name: str = "temp") -> None:
    """Remove one generated dataset, including its index and saved insights."""
    storage = get_storage()
    location = dataset_location_for_domain(temp_name, "generated")
    try:
        QdrantAdapter(temp_name).delete_dataset()
    except Exception as error:
        logger.debug("Could not delete dataset index during cleanup: %s", error)
    storage.rmtree(location.raw_rel)
    storage.rmtree(location.parsed_rel)
    storage.rmtree(location.insights_rel)


async def prepare_ephemeral_dataset(files: List[str], temp_name: str = "temp") -> str:
    """
    1. Cleans up any existing ephemeral dataset from previous runs.
    2. Sets up a temporary dataset directory.
    3. Copies the provided files into it.
    4. Runs the ingestion pipeline to parse and embed them.
    5. Returns the dataset name (e.g., 'temp') for the skill to use.
    """
    logger.info(f"Cleaning up previous ephemeral dataset '{temp_name}'...")
    await discard_ephemeral_dataset(temp_name)
    storage = get_storage()
    location = dataset_location_for_domain(temp_name, "generated")
    raw_dataset_rel = location.raw_rel

    # 2. Setup: Copy external files (absolute OS paths) into the storage tree
    storage.mkdir(raw_dataset_rel)
    for file_path in files:
        if os.path.exists(file_path):
            with open(file_path, "rb") as src:
                storage.write_bytes(f"{raw_dataset_rel}/{os.path.basename(file_path)}", src.read())
        else:
            logger.warning(f"Provided file does not exist: {file_path}")

    # 3. Ingest: Parse to markdown and embed in Qdrant
    logger.info(f"Ingesting ephemeral dataset '{temp_name}'...")
    await sync_datasets([temp_name], raise_on_error=True)

    return temp_name
