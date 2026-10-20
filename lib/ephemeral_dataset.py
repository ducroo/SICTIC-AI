import os
from pathlib import PurePosixPath
from typing import List

from lib.datasets.ingestion import sync_datasets
from lib.infrastructure.qdrant import QdrantAdapter
from lib.infrastructure.logging import get_logger
from lib.storage import get_storage
from lib.datasets.paths import dataset_location_for_domain, find_dataset_location

logger = get_logger(__name__)

async def prepare_ephemeral_dataset(files: List[str], temp_name: str = "temp") -> str:
    """
    1. Clears a generated dataset's dossier, including insights, parsed data and index.
    2. Sets up a temporary dataset directory.
    3. Copies the provided files into it.
    4. Runs the ingestion pipeline to parse and embed them.
    5. Returns the dataset name (e.g., 'temp') for the skill to use.
    """
    storage = get_storage()
    location = dataset_location_for_domain(temp_name, "generated")
    if not location.slug:
        raise ValueError("A temporary dataset requires a nonempty name.")
    existing = find_dataset_location(temp_name)
    if existing is not None and existing.domain != "generated":
        raise ValueError(f"Cannot reset permanent dataset {temp_name!r} as temporary.")
    raw_dataset_rel = location.raw_rel

    # Derive dossier directories from the configured layout, never a domain root.
    reset_paths = []
    for path, root in (
        (location.raw_rel, location.dataset_root),
        (location.insights_rel, location.insights_root),
        (location.parsed_rel, location.parsed_root),
    ):
        directory = PurePosixPath(path).parent
        if directory == PurePosixPath(root) or not directory.is_relative_to(root):
            raise ValueError(f"Unsafe temporary dataset reset directory: {directory}")
        if str(directory) not in reset_paths:
            reset_paths.append(str(directory))

    # 1. Cleanup previous run
    logger.info(f"Cleaning up previous ephemeral dataset '{temp_name}'...")
    # Keep the old dataset discoverable until its index is removed. Failure here
    # must stop the reset, rather than mixing old indexed evidence with new files.
    qdrant = QdrantAdapter(temp_name)
    qdrant.delete_dataset()
    for path in reset_paths:
        storage.rmtree(path)
        if storage.exists(path):
            raise OSError(f"Could not clear temporary dataset directory: {path}")

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
