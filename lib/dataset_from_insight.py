import time
from pathlib import PurePosixPath
from typing import Dict, List, Optional

from lib.active_dataset import is_active_dataset, activate_dataset
from lib.insight_refresh import get_base_name, best_alternative
from lib.logger import get_logger
from lib.slugify import slugify
from lib.storage import get_storage

logger = get_logger(__name__)

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
            parent_dir = name.split("/")[0] if "/" in name else ""
            
            if not source_slug and parent_dir == target_slug:
                continue

            if not source_slug and parent_dir and not is_active_dataset(parent_dir):
                continue
                
            out[f"{scan_root}/{name}"] = mtime
    return out


async def dataset_from_insight(target_dataset: str, insight: Optional[str] = None, source_dataset: Optional[str] = None):
    """
    Universally hydrates a Qdrant dataset directory from existing insights.
    Relies on lib.insight_refresh to determine base names and best alternatives.
    """
    target_slug = slugify(target_dataset)
    target_rel = f"datasets/{target_slug}"

    insight_slug = slugify(insight or target_dataset)

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

    # Group full file paths by their base entity name
    entity_to_files: Dict[str, List[str]] = {}
    for full_path in files_to_sync_dict.keys():
        filename = PurePosixPath(full_path).name
        
        # If the file has the insight prefix (e.g. startup-profile-avientus), we need to extract the entity (avientus).
        # We can simulate this by stripping the prefix before getting the base name.
        prefix = f"{insight_slug}-"
        clean_name = filename[len(prefix):] if filename.startswith(prefix) else filename
        
        base = get_base_name(clean_name)
        if base not in entity_to_files:
            entity_to_files[base] = []
        entity_to_files[base].append(full_path)

    sync_count = 0
    # For each entity, ask best_alternative for the single best file
    for base_name, full_paths in entity_to_files.items():
        # Create a list of just the filenames for the generator
        filenames = [PurePosixPath(p).name for p in full_paths]
        
        # We can just pass the first filename to best_alternative since it shares the base_name
        best_name = next(best_alternative(filenames[0], filenames), None)
        if not best_name:
            continue
            
        # Recover the full path and mtime
        best_full_path = next(p for p in full_paths if PurePosixPath(p).name == best_name)
        source_mtime = files_to_sync_dict[best_full_path]
        
        target_file_rel = f"{target_rel}/{best_name}"

        if best_name in existing_files:
            target_mtime = existing_files[best_name]
            del existing_files[best_name]
            
            # If target is newer than or identical to source, skip sync
            if target_mtime >= (source_mtime - 1.0):
                logger.debug(f"Skipped {best_name} (unchanged/up-to-date)")
                continue

        try:
            storage.write_bytes(target_file_rel, storage.read_bytes(best_full_path))
            logger.debug(f"Synced {best_full_path} -> {target_file_rel}")
            sync_count += 1
        except Exception as e:
            logger.error(f"Failed to sync {best_full_path}: {e}")
            
    orphan_count = 0
    for orphan in list(existing_files.keys()):
        try:
            if hasattr(storage, 'delete'):
                storage.delete(f"{target_rel}/{orphan}")
            else:
                storage.rmtree(f"{target_rel}/{orphan}")
            orphan_count += 1
        except Exception as e:
            logger.warning(f"Failed to remove orphaned file {orphan}: {e}")

    logger.info(f"Dataset hydration complete. {sync_count} files synced, {orphan_count} removed, {len(entity_to_files) - sync_count} unchanged.")
