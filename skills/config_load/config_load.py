import json
from pathlib import Path
from typing import Any, Dict

from lib.env import get_env_var
from lib.logger import get_logger

logger = get_logger(__name__)

# The single source of truth is now the local Git repository's config folder.
REPO_ROOT = Path(get_env_var("REPO_PATH"))
SOURCE_DIR = REPO_ROOT / "config"

def _local_cache_paths() -> tuple[Path, Path]:
    """Local cache lives in the configured REPO_PATH/cache."""
    cache_dir = REPO_ROOT / "cache"
    cache_file = cache_dir / "config.json"
    return cache_dir, cache_file

def _build_tree_from_local_files(md_files: list[Path]) -> Dict[str, Any]:
    """Given a list of local .md file Paths, build the nested config dict.
    Directory entries are inferred from path segments relative to SOURCE_DIR.
    """
    tree: Dict[str, Any] = {}
    for filepath in md_files:
        # Get the path relative to the config/ root
        try:
            relpath = filepath.relative_to(SOURCE_DIR)
        except ValueError:
            logger.warning(f"File {filepath} is not relative to {SOURCE_DIR}. Skipping.")
            continue
            
        parts = relpath.parts
        stem = filepath.stem
        
        cur = tree
        # Traverse/create the nested dictionary structure using directory names
        for segment in parts[:-1]:
            existing = cur.get(segment)
            if not isinstance(existing, dict):
                existing = {}
                cur[segment] = existing
            cur = existing
            
        try:
            content = filepath.read_text(encoding="utf-8").strip()
        except Exception as e:
            logger.warning(f"Failed to read local config file {filepath}: {e}")
            content = ""
            
        cur[stem] = content
        
    return tree

def config_load() -> Dict[str, Any]:
    cache_dir, cache_file = _local_cache_paths()

    if not SOURCE_DIR.exists() or not SOURCE_DIR.is_dir():
        logger.error(f"Cannot find local config directory at {SOURCE_DIR}.")
        return {}

    # Find every .md file recursively in the local config directory
    md_files = list(SOURCE_DIR.rglob("*.md"))
    
    if not md_files:
        logger.error(f"Cannot rebuild cache: no .md files found in {SOURCE_DIR}.")
        return {}

    # Find the most recently modified file to check against the cache
    latest_source_mtime = max((f.stat().st_mtime for f in md_files), default=0.0)

    # Fresh cache hit?
    if cache_file.exists():
        cache_mtime = cache_file.stat().st_mtime
        if cache_mtime >= latest_source_mtime:
            try:
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.error(f"Failed to load existing cache file: {e}. Rebuilding...")

    # Rebuild from local Git files
    config_data = _build_tree_from_local_files(md_files)

    # Persist to local cache
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        cache_file.write_text(json.dumps(config_data, indent=4), encoding="utf-8")
        logger.info(f"Rebuilt config cache successfully from {len(md_files)} local files.")
    except OSError as e:
        logger.error(f"Error writing cache file: {e}")

    return config_data
