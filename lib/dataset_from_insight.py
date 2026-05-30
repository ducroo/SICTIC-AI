import time
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Dict, List, Optional

from lib.active_dataset import is_active_dataset, activate_dataset
from lib.insight_refresh import get_base_name, best_alternative
from lib.logger import get_logger
from lib.slugify import slugify
from lib.storage import get_storage
from lib.storage_domains import dataset_insights_path, dataset_raw_path, storage_domain_config

logger = get_logger(__name__)


@dataclass(frozen=True)
class DatasetFromInsightResult:
    target_dataset: str
    target_path: str
    insight: str
    source_dataset: Optional[str]
    candidates: int = 0
    entities: int = 0
    selected: int = 0
    synced: int = 0
    removed: int = 0
    unchanged: int = 0
    dry_run: bool = False


def _gather_insight_files(insight_slug: str, source_dataset: Optional[str], target_slug: str) -> Dict[str, float]:
    """Find relevant markdown files for an insight. Returns path -> mtime.

    Canonical subdirectory insights are stored as:
        insights/<domain>/<dataset>/<insight-slug>/<identifier>-<model>.md

    Root-level insights are stored as:
        insights/<domain>/<dataset>/<insight-slug>-<dataset>-<model>.md

    The subdirectory name is therefore the source of truth for subdir insights;
    filenames inside the directory do not repeat the skill name.
    """
    storage = get_storage()
    source_slug = slugify(source_dataset) if source_dataset else None
    scan_roots = [dataset_insights_path(source_slug)] if source_slug else [
        domain["insights_root"].strip("/")
        for domain in storage_domain_config()["domains"].values()
    ]

    out = {}
    for scan_root in dict.fromkeys(scan_roots):
        if not storage.exists(scan_root):
            continue
        for name, mtime in storage.list_with_mtime(scan_root, recursive=True):
            if not name.endswith(".md"):
                continue

            parts = PurePosixPath(name).parts
            parent_dir = parts[0] if len(parts) > 1 else ""
            filename = parts[-1]
            in_insight_subdir = len(parts) > 1 and parts[-2] == insight_slug
            is_root_insight_file = not parent_dir and filename.startswith(f"{insight_slug}-")

            if not in_insight_subdir and not is_root_insight_file:
                continue

            if not source_slug and parent_dir == target_slug:
                continue

            if not source_slug and parent_dir and not is_active_dataset(parent_dir):
                continue

            out[f"{scan_root}/{name}"] = mtime
    return out


async def dataset_from_insight(
    target_dataset: str,
    insight: Optional[str] = None,
    source_dataset: Optional[str] = None,
    *,
    dry_run: bool = False,
) -> DatasetFromInsightResult:
    """
    Universally hydrates a Qdrant dataset directory from existing insights.
    Relies on lib.insight_refresh to determine base names and best alternatives.
    """
    target_slug = slugify(target_dataset)
    target_rel = dataset_raw_path(target_slug)

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
        return DatasetFromInsightResult(
            target_dataset=target_slug,
            target_path=target_rel,
            insight=insight_slug,
            source_dataset=source_dataset,
            dry_run=dry_run,
        )

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

    selected_count = 0
    sync_count = 0
    unchanged_count = 0
    # For each entity, ask best_alternative for the single best file
    for base_name, full_paths in entity_to_files.items():
        # Create a list of just the filenames for the generator
        filenames = [PurePosixPath(p).name for p in full_paths]
        
        # We can just pass the first filename to best_alternative since it shares the base_name
        best_name = next(best_alternative(filenames[0], filenames), None)
        if not best_name:
            continue
        selected_count += 1
            
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
                unchanged_count += 1
                continue

        try:
            if dry_run:
                logger.info(f"[dry-run] Would sync {best_full_path} -> {target_file_rel}")
            else:
                storage.write_bytes(target_file_rel, storage.read_bytes(best_full_path))
            logger.debug(f"Synced {best_full_path} -> {target_file_rel}")
            sync_count += 1
        except Exception as e:
            logger.error(f"Failed to sync {best_full_path}: {e}")
            
    orphan_count = 0
    for orphan in list(existing_files.keys()):
        try:
            orphan_rel = f"{target_rel}/{orphan}"
            if dry_run:
                logger.info(f"[dry-run] Would remove orphaned file {orphan_rel}")
            else:
                # Orphans are individual derived markdown files. Use remove(),
                # not rmtree(), otherwise LocalStorage leaves stale files behind
                # and the next Qdrant sync cannot delete their old chunks.
                storage.remove(orphan_rel)
            orphan_count += 1
        except Exception as e:
            logger.warning(f"Failed to remove orphaned file {orphan}: {e}")

    logger.info(
        "Dataset hydration complete. "
        f"{sync_count} files synced, {orphan_count} removed, {unchanged_count} unchanged."
    )
    return DatasetFromInsightResult(
        target_dataset=target_slug,
        target_path=target_rel,
        insight=insight_slug,
        source_dataset=source_dataset,
        candidates=len(files_to_sync_dict),
        entities=len(entity_to_files),
        selected=selected_count,
        synced=sync_count,
        removed=orphan_count,
        unchanged=unchanged_count,
        dry_run=dry_run,
    )
