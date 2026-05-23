import time
from pathlib import PurePosixPath
from typing import Dict, List, Optional

from lib.env import get_env_var
from lib.logger import get_logger
from lib.slugify import slugify
from lib.storage import get_storage

logger = get_logger(__name__)


def _get_model_priority(filename: str, ranked_models: List[str]) -> int:
    """
    Returns the priority of the model used in the filename based on RANKED_LLMS.
    Lower number = higher priority. 0 is best.
    If not found, returns infinity.
    """
    stem = PurePosixPath(filename).stem
    for i, model in enumerate(ranked_models):
        if model in stem:
            return i
    return float('inf')


def _wipe_target_directory(target_rel: str) -> None:
    """Wipes the target dataset directory by moving it to a central trash folder."""
    storage = get_storage(get_env_var("REPOSITORY_DIR"))
    if storage.exists(target_rel):
        logger.info(f"Wiping existing target directory: {target_rel}")
        name = PurePosixPath(target_rel).name
        trash_rel = f"trash/{name}_trash_{int(time.time())}"
        try:
            # Move-then-recreate: read source files, write into trash, delete source.
            # Storage has no rename; rmtree gives us the same end state.
            storage.rmtree(target_rel)
            logger.debug(f"Removed old directory {target_rel} (trash path would have been {trash_rel})")
        except Exception as e:
            logger.warning(f"Failed to wipe {target_rel}: {e}")
    storage.mkdir(target_rel)


def _gather_insight_files(insight_lower: str, source_dataset: Optional[str]) -> List[str]:
    """Finds all relevant markdown files for the given insight recursively. Returns storage-relative paths."""
    storage = get_storage(get_env_var("REPOSITORY_DIR"))
    scan_root = f"insights/{source_dataset.lower()}" if source_dataset else "insights"

    if not storage.exists(scan_root):
        return []

    insight_slug = slugify(insight_lower)

    out = []
    for name, _mtime in storage.list_with_mtime(scan_root, recursive=True):
        if name.endswith(".md") and insight_slug in PurePosixPath(name).name:
            out.append(f"{scan_root}/{name}")
    return out


def _group_files_by_entity(files: List[str], insight_lower: str) -> Dict[str, List[str]]:
    """Groups files by their entity prefix to resolve versions."""
    grouped_files: Dict[str, List[str]] = {}
    insight_slug = slugify(insight_lower)
    separator = f"-{insight_slug}-"

    for src_file in files:
        base_name = PurePosixPath(src_file).stem
        if separator not in base_name:
            err_msg = f"File '{PurePosixPath(src_file).name}' does not match the expected naming convention (missing separator '{separator}')."
            logger.error(err_msg)
            raise ValueError(err_msg)

        entity_name = base_name.split(separator)[0]

        if entity_name not in grouped_files:
            grouped_files[entity_name] = []
        grouped_files[entity_name].append(src_file)

    return grouped_files


def _sync_best_candidates(grouped_files: Dict[str, List[str]], target_rel: str, ranked_models: List[str]) -> int:
    """Selects the best model file per entity and copies it to the target."""
    storage = get_storage(get_env_var("REPOSITORY_DIR"))
    sync_count = 0
    for entity_name, candidate_files in grouped_files.items():
        best_file = min(candidate_files, key=lambda f: _get_model_priority(PurePosixPath(f).name, ranked_models))
        target_file_rel = f"{target_rel}/{PurePosixPath(best_file).name}"

        try:
            storage.write_bytes(target_file_rel, storage.read_bytes(best_file))
            logger.debug(f"Synced {best_file} -> {target_file_rel}")
            sync_count += 1
        except Exception as e:
            logger.error(f"Failed to sync {best_file}: {e}")

    return sync_count


async def dataset_from_insight(target_dataset: str, insight: Optional[str] = None, source_dataset: Optional[str] = None):
    """
    Universally hydrates a Qdrant dataset directory from existing insights.

    1. Wipes the target dataset directory clean.
    2. Gathers files matching the insight.
    3. Resolves multiple versions of the same file by picking the one with the best model
       based on RANKED_LLMS priority.
    4. Copies files to the target directory while preserving original filenames.
    """
    target_rel = f"datasets/{target_dataset.lower()}"

    insight_lower = (insight or target_dataset).lower()

    raw_llms = get_env_var("RANKED_LLMS")
    ranked_models = [slugify(m.split('/')[-1]) for m in raw_llms.split(",") if m.strip()]

    logger.info(f"Hydrating dataset '{target_dataset}' from insight '{insight_lower}'...")

    _wipe_target_directory(target_rel)

    files_to_sync = _gather_insight_files(insight_lower, source_dataset)
    if not files_to_sync:
        logger.warning(f"No files matching insight '{insight_lower}' found in specified sources.")
        return

    logger.info(f"Found {len(files_to_sync)} insight files to evaluate for syncing.")

    grouped_files = _group_files_by_entity(files_to_sync, insight_lower)

    sync_count = _sync_best_candidates(grouped_files, target_rel, ranked_models)

    logger.info(f"Dataset hydration complete. {sync_count} files synced to {target_dataset}.")
