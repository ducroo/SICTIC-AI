import json
from pathlib import Path
from typing import Any, Dict

from lib.env import get_env_var
from lib.storage import get_storage
from lib.logger import get_logger

logger = get_logger(__name__)


SOURCE_REL = "config"


def _local_cache_paths() -> tuple[Path, Path]:
    """Local cache lives outside the storage abstraction — it's a derivative."""
    workspace_dir = Path(get_env_var("WORKSPACE_DIR"))
    cache_dir = workspace_dir / "cache"
    cache_file = cache_dir / "config.json"
    return cache_dir, cache_file


def _build_tree_from_flat_files(files: list[tuple[str, float]]) -> Dict[str, Any]:
    """Given (relpath, mtime) pairs for every .md under SOURCE_REL, build the nested config dict.
    Directory entries are inferred from path segments; file contents are read on demand.
    """
    storage = get_storage(get_env_var("REPOSITORY_DIR"))
    tree: Dict[str, Any] = {}
    for relpath, _mt in files:
        parts = relpath.split("/")
        stem = parts[-1][:-3] if parts[-1].lower().endswith(".md") else parts[-1]
        cur = tree
        for segment in parts[:-1]:
            existing = cur.get(segment)
            if not isinstance(existing, dict):
                existing = {}
                cur[segment] = existing
            cur = existing
        try:
            content = storage.read_text(f"{SOURCE_REL}/{relpath}").strip()
        except Exception as e:
            logger.warning(f"Failed to read config file {relpath}: {e}")
            content = ""
        cur[stem] = content
    return tree


def config_load() -> Dict[str, Any]:
    cache_dir, cache_file = _local_cache_paths()
    storage = get_storage(get_env_var("REPOSITORY_DIR"))

    # Find every .md under SOURCE_REL (recursive) along with its mtime.
    try:
        all_items = storage.list_with_mtime(SOURCE_REL, recursive=True)
        md_files = [(name, mt) for name, mt in all_items if name.lower().endswith(".md")]
    except Exception as e:
        logger.warning(f"Cannot enumerate {SOURCE_REL!r} on storage ({e}); falling back to cache if present.")
        md_files = []

    latest_source_mtime = max((mt for _, mt in md_files), default=0.0)

    # Fresh cache hit?
    if cache_file.exists():
        cache_mtime = cache_file.stat().st_mtime
        if cache_mtime >= latest_source_mtime:
            try:
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.error(f"Failed to load existing cache file: {e}. Rebuilding...")

    if not md_files:
        logger.error(f"Cannot rebuild cache: no .md files found at storage path {SOURCE_REL!r}.")
        return {}

    config_data = _build_tree_from_flat_files(md_files)

    # Persist to local cache (derivative artifact — stays on disk, not on Drive).
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        cache_file.write_text(json.dumps(config_data, indent=4), encoding="utf-8")
    except OSError as e:
        logger.error(f"Error writing cache file: {e}")

    return config_data
