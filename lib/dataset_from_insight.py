import time
from pathlib import PurePosixPath
from typing import Dict, List, Optional

from lib.active_dataset import is_active_dataset, activate_dataset
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



def _gather_insight_files(insight_slug: str, source_dataset: Optional[str], target_slug: str) -> Dict[str, float]:
    """Finds all relevant markdown files for the given insight recursively. Returns dict of path -> mtime."""
    storage = get_storage()
    source_slug = slugify(source_dataset) if source_dataset else None
    scan_root = f"insights/{source_slug}" if source_slug else "insights"

    if not storage.exists(scan_root):
        return {}

    out = {}
    for name, mtime in storage.list_with_mtime(scan_root, recursive=True):
        if name.endswith(".md") and insight_slug in name:
            # Extract the dataset/entity folder name (e.g. 'avientus' from 'avientus/startup-profile-avientus-gpt-4o.md')
            # or in subdir logic: 'person-profile' from 'person-profile/urs-gubser-gemma.md'
            parent_dir = name.split("/")[0] if "/" in name else ""
            
            # Prevent picking up files from the target dataset itself if doing a global scan
            # We must use source_slug to determine if it's a global scan
            if not source_slug and parent_dir == target_slug:
                continue

            # If doing a global scan, only include files from active datasets
            if not source_slug and parent_dir and not is_active_dataset(parent_dir):
                continue
                
            out[f"{scan_root}/{name}"] = mtime
    return out


def _group_files_by_entity(files_dict: Dict[str, float], insight_slug: str, ranked_models: List[str]) -> Dict[str, List[str]]:
    """Groups files by their entity prefix to resolve versions."""
    grouped_files: Dict[str, List[str]] = {}
    
    # We expect files to look like: <insight_slug>-<entity>-<model_slug>.md OR <entity>-<model_slug>.md (in subdir)
    prefix = f"{insight_slug}-"

    for src_file in files_dict.keys():
        base_name = PurePosixPath(src_file).stem
        
        # If it has the prefix (e.g. startup-profile-avientus), strip it. Otherwise use the raw name (e.g. urs-gubser).
        if base_name.startswith(prefix):
            remainder = base_name[len(prefix):]
        else:
            remainder = base_name
        
        # Strip the known model suffix if present
        entity_name = remainder
        for model in ranked_models:
            model_suffix = f"-{model}"
            if remainder.endswith(model_suffix):
                entity_name = remainder[:-len(model_suffix)]
                break

        if entity_name not in grouped_files:
            grouped_files[entity_name] = []
        grouped_files[entity_name].append(src_file)

    return grouped_files


def _sync_best_candidates(grouped_files: Dict[str, List[str]], source_mtimes: Dict[str, float], target_rel: str, existing_files: Dict[str, float], ranked_models: List[str]) -> int:
    """Selects the best model file per entity and copies it to the target if missing or changed."""
    storage = get_storage()
    sync_count = 0
    for entity_name, candidate_files in grouped_files.items():
        best_file = min(candidate_files, key=lambda f: _get_model_priority(PurePosixPath(f).name, ranked_models))
        best_file_name = PurePosixPath(best_file).name
        target_file_rel = f"{target_rel}/{best_file_name}"
        source_mtime = source_mtimes[best_file]

        if best_file_name in existing_files:
            target_mtime = existing_files[best_file_name]
            del existing_files[best_file_name]
            
            # Check timestamp (allowing a small jitter margin for Google Drive)
            if abs(target_mtime - source_mtime) < 1.0:
                logger.debug(f"Skipped {best_file_name} (unchanged)")
                continue

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
    5. Writes an active dataset marker if files were successfully synced.
    """
    target_slug = slugify(target_dataset)
    target_rel = f"datasets/{target_slug}"

    insight_slug = slugify(insight or target_dataset)

    raw_llms = get_env_var("RANKED_LLMS")
    ranked_models = [slugify(m.split('/')[-1]) for m in raw_llms.split(",") if m.strip()]

    logger.info(f"Hydrating dataset '{target_slug}' from insight '{insight_slug}'...")

    storage = get_storage()
    if not storage.exists(target_rel):
        storage.mkdir(target_rel)
        existing_files = {}
    else:
        existing_files = {
            PurePosixPath(name).name: mtime 
            for name, mtime in storage.list_with_mtime(target_rel)
        }

    files_to_sync_dict = _gather_insight_files(insight_slug, source_dataset, target_slug)
    if not files_to_sync_dict:
        logger.warning(f"No files matching insight '{insight_slug}' found in specified sources.")
        return

    logger.info(f"Found {len(files_to_sync_dict)} insight files to evaluate for syncing.")

    grouped_files = _group_files_by_entity(files_to_sync_dict, insight_slug, ranked_models)

    sync_count = _sync_best_candidates(grouped_files, files_to_sync_dict, target_rel, existing_files, ranked_models)
    
    orphan_count = 0
    for orphan in list(existing_files.keys()):
        try:
            # We attempt standard delete on the storage backend
            if hasattr(storage, 'delete'):
                storage.delete(f"{target_rel}/{orphan}")
            else:
                storage.rmtree(f"{target_rel}/{orphan}")
            orphan_count += 1
        except Exception as e:
            logger.warning(f"Failed to remove orphaned file {orphan}: {e}")

    logger.info(f"Dataset hydration complete. {sync_count} files synced, {orphan_count} removed, {len(grouped_files) - sync_count} unchanged.")
