import os
import shutil
import asyncio
from pathlib import Path
from typing import Optional, Dict, List

from skills.utils.logger import get_logger
from skills.utils.env import get_env_var
from skills.utils.slugify import slugify

logger = get_logger(__name__)

def _get_model_priority(filename: str, ranked_models: List[str]) -> int:
    """
    Returns the priority of the model used in the filename based on RANKED_LLMS.
    Lower number = higher priority. 0 is best.
    If not found, returns infinity.
    """
    stem = Path(filename).stem
    for i, model in enumerate(ranked_models):
        if model in stem:
            return i
    return float('inf')

def _wipe_target_directory(target_dir: Path, gdrive_mount: Path) -> None:
    """Wipes the target dataset directory cleanly by moving it to a central trash folder."""
    if target_dir.exists():
        logger.info(f"Wiping existing target directory: {target_dir}")
        import time
        trash_base = gdrive_mount / "trash"
        trash_base.mkdir(parents=True, exist_ok=True)
        
        trash_dir = trash_base / f"{target_dir.name}_trash_{int(time.time())}"
        try:
            target_dir.rename(trash_dir)
            logger.debug(f"Moved old directory to {trash_dir}")
        except Exception as e:
            logger.warning(f"Failed to move {target_dir} to trash: {e}")
    target_dir.mkdir(parents=True, exist_ok=True)

def _gather_insight_files(insights_base: Path, insight_lower: str, source_dataset: Optional[str]) -> List[Path]:
    """Finds all relevant markdown files for the given insight recursively."""
    scan_root = insights_base / source_dataset.lower() if source_dataset else insights_base
    
    if not scan_root.exists() or not scan_root.is_dir():
        return []
        
    insight_slug = slugify(insight_lower)
    
    # Recursively find all .md files containing the slugified insight name
    return [f for f in scan_root.rglob("*.md") if f.is_file() and insight_slug in f.name]

def _group_files_by_entity(files: List[Path], insight_lower: str) -> Dict[str, List[Path]]:
    """Groups files by their entity prefix to resolve versions."""
    grouped_files: Dict[str, List[Path]] = {}
    insight_slug = slugify(insight_lower)
    separator = f"-{insight_slug}-"
    
    for src_file in files:
        base_name = src_file.stem
        if separator not in base_name:
            err_msg = f"File '{src_file.name}' does not match the expected naming convention (missing separator '{separator}')."
            logger.error(err_msg)
            raise ValueError(err_msg)
            
        entity_name = base_name.split(separator)[0]
        
        if entity_name not in grouped_files:
            grouped_files[entity_name] = []
        grouped_files[entity_name].append(src_file)
        
    return grouped_files

def _sync_best_candidates(grouped_files: Dict[str, List[Path]], target_dir: Path, ranked_models: List[str]) -> int:
    """Selects the best model file per entity and copies it to the target."""
    sync_count = 0
    for entity_name, candidate_files in grouped_files.items():
        best_file = min(candidate_files, key=lambda f: _get_model_priority(f.name, ranked_models))
        
        target_file = target_dir / best_file.name
        
        try:
            shutil.copy2(best_file, target_file)
            logger.debug(f"Synced {best_file.name} -> {target_file.name}")
            sync_count += 1
        except Exception as e:
            logger.error(f"Failed to sync {best_file.name}: {e}")
            
    return sync_count

async def dataset_from_insight(target_dataset: str, insight: Optional[str] = None, source_dataset: Optional[str] = None):
    """
    Universally hydrates a Qdrant dataset directory from existing insights.
    
    1. Wipes the target dataset directory clean.
    2. Gathers files matching the insight.
    3. Resolves multiple versions of the same file by picking the one with the best model
       based on RANKED_LLMS priority.
    4. Copies files to the target directory while preserving original timestamps and filenames.
    """
    gdrive_mount = Path(get_env_var("GDRIVE_MOUNT"))
    insights_base = gdrive_mount / "insights"
    target_dir = gdrive_mount / "datasets" / target_dataset.lower()
    
    insight_lower = (insight or target_dataset).lower()
    
    raw_llms = get_env_var("RANKED_LLMS")
    ranked_models = [slugify(m.split('/')[-1]) for m in raw_llms.split(",") if m.strip()]
    
    logger.info(f"Hydrating dataset '{target_dataset}' from insight '{insight_lower}'...")

    _wipe_target_directory(target_dir, gdrive_mount)

    files_to_sync = _gather_insight_files(insights_base, insight_lower, source_dataset)
    if not files_to_sync:
        logger.warning(f"No files matching insight '{insight_lower}' found in specified sources.")
        return
        
    logger.info(f"Found {len(files_to_sync)} insight files to evaluate for syncing.")

    grouped_files = _group_files_by_entity(files_to_sync, insight_lower)
    
    sync_count = _sync_best_candidates(grouped_files, target_dir, ranked_models)
            
    logger.info(f"Dataset hydration complete. {sync_count} files synced to {target_dataset}.")
