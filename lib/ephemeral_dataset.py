import os
from pathlib import PurePosixPath
from typing import List

from lib.datasets.ingestion import sync_datasets
from lib.infrastructure.qdrant import QdrantAdapter
from lib.infrastructure.logging import get_logger
from lib.storage import get_storage
from lib.datasets.paths import dataset_location_for_domain, find_dataset_location

logger = get_logger(__name__)


async def discard_ephemeral_dataset(temp_name: str = "temp") -> None:
    """Remove a generated dossier and index; preserve files if index cleanup fails."""
    storage = get_storage()
    location = dataset_location_for_domain(temp_name, "generated")
    if not location.slug:
        raise ValueError("A temporary dataset requires a nonempty name.")
    existing = find_dataset_location(temp_name)
    if existing is not None and existing.domain != "generated":
        raise ValueError(f"Cannot reset permanent dataset {temp_name!r} as temporary.")

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


async def prepare_ephemeral_dataset(
    files: List[str],
    temp_name: str = "temp",
    *,
    relative_paths: List[str] | None = None,
) -> str:
    """
    1. Clears a generated dataset's dossier, including insights, parsed data and index.
    2. Sets up a temporary dataset directory.
    3. Copies the provided files into it.
    4. Runs the ingestion pipeline to parse and embed them.
    5. Returns the dataset name (e.g., 'temp') for the skill to use.

    When ``relative_paths`` is set, each entry is the destination path under the
    dataset raw folder for the matching ``files`` item (same length required).
    Otherwise each file is stored under its basename.
    """
    if relative_paths is not None and len(relative_paths) != len(files):
        raise ValueError("relative_paths must match files one-for-one.")

    await discard_ephemeral_dataset(temp_name)
    storage = get_storage()
    location = dataset_location_for_domain(temp_name, "generated")
    raw_dataset_rel = location.raw_rel

    # 2. Setup: Copy external files (absolute OS paths) into the storage tree
    storage.mkdir(raw_dataset_rel)
    for index, file_path in enumerate(files):
        if not os.path.exists(file_path):
            logger.warning(f"Provided file does not exist: {file_path}")
            continue
        if relative_paths is None:
            dest_name = os.path.basename(file_path)
        else:
            dest = PurePosixPath(relative_paths[index].replace("\\", "/"))
            if dest.is_absolute() or ".." in dest.parts or not dest.name:
                raise ValueError(f"Unsafe ephemeral destination: {relative_paths[index]!r}")
            dest_name = dest.as_posix()
            parent = PurePosixPath(dest_name).parent
            if str(parent) not in {".", ""}:
                storage.mkdir(f"{raw_dataset_rel}/{parent.as_posix()}")
        with open(file_path, "rb") as src:
            storage.write_bytes(f"{raw_dataset_rel}/{dest_name}", src.read())

    # 3. Ingest: Parse to markdown and embed in Qdrant
    logger.info(f"Ingesting ephemeral dataset '{temp_name}'...")
    await sync_datasets([temp_name], raise_on_error=True)

    return temp_name
