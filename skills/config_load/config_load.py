import json
import os
from pathlib import Path
from typing import Any, Dict

from lib.env import get_env_var
from lib.logger import get_logger

logger = get_logger(__name__)

def _repo_root() -> Path:
    return Path(get_env_var("REPO_PATH")).expanduser()


def _source_dir() -> Path:
    # The single source of truth is the local Git repository's config folder.
    return _repo_root() / "config"


def _local_data_root() -> Path:
    configured = os.environ.get("LOCAL_DATA_PATH") or get_env_var("REPO_PATH")
    root = Path(configured).expanduser()
    if not root.is_absolute():
        raise ValueError(f"LOCAL_DATA_PATH must be absolute, got: {configured}")
    return root

def _local_cache_paths() -> tuple[Path, Path]:
    """Local config cache lives under LOCAL_DATA_PATH/cache."""
    cache_dir = _local_data_root() / "cache"
    cache_file = cache_dir / "config.json"
    return cache_dir, cache_file

def _build_tree_from_local_files(md_files: list[Path], source_dir: Path) -> Dict[str, Any]:
    """Given a list of local .md file Paths, build the nested config dict.
    Directory entries are inferred from path segments relative to source_dir.
    """
    tree: Dict[str, Any] = {}
    for filepath in md_files:
        # Get the path relative to the config/ root
        try:
            relpath = filepath.relative_to(source_dir)
        except ValueError:
            logger.warning(f"File {filepath} is not relative to {source_dir}. Skipping.")
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
    source_dir = _source_dir()
    cache_dir, cache_file = _local_cache_paths()

    if not source_dir.exists() or not source_dir.is_dir():
        logger.error(f"Cannot find local config directory at {source_dir}.")
        return {}

    # Find every .md file recursively in the local config directory
    md_files = list(source_dir.rglob("*.md"))
    
    if not md_files:
        logger.error(f"Cannot rebuild cache: no .md files found in {source_dir}.")
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
    config_data = _build_tree_from_local_files(md_files, source_dir)

    # Persist to local cache
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        cache_file.write_text(json.dumps(config_data, indent=4), encoding="utf-8")
        logger.info(f"Rebuilt config cache successfully from {len(md_files)} local files.")
    except OSError as e:
        logger.error(f"Error writing cache file: {e}")

    return config_data
