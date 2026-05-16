import json
import os
from pathlib import Path
from typing import Any, Dict, Union

from skills.utils.env import get_env_var
from skills.utils.logger import get_logger

logger = get_logger(__name__)


# logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# Repo root = three directories up from this file (skills/config_load/config_load.py).
_REPO_ROOT = Path(__file__).resolve().parents[2]


def get_base_paths():
    workspace_dir_str = get_env_var("WORKSPACE_DIR")
    workspace_dir = Path(workspace_dir_str)
    # Config is in-repo (git-tracked), not on Drive. Anchored to the repo so it
    # works regardless of where the repo is checked out.
    source_dir = _REPO_ROOT / "config"
    cache_dir = workspace_dir / "cache"
    cache_file = cache_dir / "config.json"
    return workspace_dir, source_dir, cache_dir, cache_file

def get_latest_mtime(directory: Path) -> float:
    latest = 0.0
    for file in directory.rglob("*.md"):
        try:
            mtime = file.stat().st_mtime
            if mtime > latest:
                latest = mtime
        except OSError:
            pass
    return latest

def build_config_tree(directory: Path) -> Union[Dict[str, Any], str]:
    tree: Dict[str, Any] = {}
    try:
        items = sorted(directory.iterdir())
    except PermissionError as e:
        logger.error(f"Permission error reading {directory}: {e}")
        return ""
    except OSError as e:
        logger.error(f"OS error reading {directory}: {e}")
        return ""

    has_content = False
    for item in items:
        if item.is_dir():
            subtree = build_config_tree(item)
            tree[item.name] = subtree
            has_content = True
        elif item.is_file() and item.suffix.lower() == ".md":
            try:
                content = item.read_text(encoding="utf-8").strip()
                tree[item.stem] = content
                has_content = True
            except Exception as e:
                logger.warning(f"Warning: Failed to read {item}: {e}")
                tree[item.stem] = ""
                has_content = True

    if not has_content:
        return ""
    return tree

def config_load() -> Dict[str, Any]:
    workspace_dir, source_dir, cache_dir, cache_file = get_base_paths()

    latest_source_mtime = 0.0
    if source_dir.exists() and source_dir.is_dir():
        latest_source_mtime = get_latest_mtime(source_dir)
    else:
        logger.warning(f"Source path not found at {source_dir}. Attempting to use cache.")
    
    if cache_file.exists():
        cache_mtime = cache_file.stat().st_mtime
        if cache_mtime >= latest_source_mtime:
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load existing cache file: {e}. Rebuilding...")

    if not source_dir.exists() or not source_dir.is_dir():
        logger.error(f"Cannot rebuild cache: Source path not found at {source_dir}.")
        return {}

    cache_dir.mkdir(parents=True, exist_ok=True)
    config_data = build_config_tree(source_dir)

    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)
    except OSError as e:
        logger.error(f"Error writing cache file: {e}")

    return config_data
