import os
from pathlib import Path
from typing import List, Tuple, Optional
from skills.utils.env import get_env_var
from skills.utils.logger import get_logger
from skills.utils.slugify import slugify

logger = get_logger(__name__)

def get_acceptable_models(current_model_suffix: str) -> List[str]:
    raw_acceptable = ""
    try:
        raw_acceptable = get_env_var("RANKED_LLMS")
    except Exception:
        pass
        
    acceptable_list = [s.strip() for s in raw_acceptable.split(",") if s.strip()]
    
    slugified_acceptable = [slugify(m) for m in acceptable_list]
    slugified_current = slugify(current_model_suffix)
    
    models = []
    for m in slugified_acceptable:
        if m not in models:
            models.append(m)
            
    if slugified_current not in models:
        models.append(slugified_current)
        
    return models

def check_insight_refresh(datasets: List[str], file_path: str, model_name: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Returns (needs_refresh, content, matched_file_path).
    Iterates through acceptable LLM outputs by swapping the model_name part of the file_path
    and checks if one is up to date against ALL provided datasets.
    """
    gdrive_mount = get_env_var("GDRIVE_MOUNT")
    gdrive_path = Path(gdrive_mount)
    
    models = get_acceptable_models(model_name)
    current_model_slug = slugify(model_name)
    
    dataset_dirs = []
    for name in datasets:
        d_dir = gdrive_path / "datasets" / name.lower()
        if d_dir.exists():
            dataset_dirs.append(d_dir)
            
    for m in models:
        # Swap the current model slug in the file path with the acceptable model slug
        # Note: we swap specifically "-{current_model_slug}.md" to avoid partial replacements elsewhere
        candidate_path = Path(file_path.replace(f"-{current_model_slug}.md", f"-{m}.md"))
        
        if candidate_path.exists():
            candidate_mtime = candidate_path.stat().st_mtime
            
            is_valid = True
            for d_dir in dataset_dirs:
                for f in d_dir.rglob("*"):
                    if f.is_file() and f.stat().st_mtime > candidate_mtime:
                        is_valid = False
                        break
                if not is_valid:
                    break
                    
            if is_valid:
                logger.info(f"Using valid cached insight: {candidate_path.name}")
                try:
                    with open(candidate_path, "r", encoding="utf-8") as f:
                        return False, f.read(), str(candidate_path)
                except Exception as e:
                    logger.warning(f"Failed to read cache {candidate_path}: {e}")
                    
    logger.info(f"No valid cache found for {file_path}. Refresh needed.")
    return True, None, None
