from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from lib.datasets.manifest import IngestionManifest
from lib.datasets.paths import dataset_location
from lib.insights.locking import atomic_write, manifest_write_lock
from lib.logger import get_logger

logger = get_logger(__name__)

MANIFEST_VERSION = 1


@lru_cache(maxsize=256)
def prompt_hash(prompt_key: str) -> str:
    return hashlib.sha256(prompt_key.encode("utf-8")).hexdigest()


def dataset_revisions(
    storage,
    source_datasets: list[str],
) -> dict[str, str] | None:
    revisions = {}
    for name in sorted(set(source_datasets)):
        location = dataset_location(name)
        manifest = IngestionManifest.load(storage, location.parsed_rel)
        if not manifest.indexed_dataset_revision:
            return None
        revisions[location.slug] = manifest.indexed_dataset_revision
    return revisions


def load_insight_manifest(storage, path: str) -> dict:
    if not storage.exists(path):
        return {"version": MANIFEST_VERSION, "entries": {}}
    try:
        manifest = json.loads(storage.read_text(path))
        if (
            manifest.get("version") != MANIFEST_VERSION
            or not isinstance(manifest.get("entries"), dict)
        ):
            raise ValueError("unsupported insight manifest")
        return manifest
    except Exception as error:
        logger.warning(
            "Ignoring invalid insight manifest %s: %s",
            path,
            error,
        )
        return {"version": MANIFEST_VERSION, "entries": {}}


def save_insight_entry(
    storage,
    *,
    manifest_path: str,
    insight_path: str,
    model: str,
    revisions: dict[str, str],
    prompt_key: str,
) -> None:
    local_manifest = Path(storage.local_path(manifest_path))
    with manifest_write_lock(local_manifest):
        manifest = load_insight_manifest(storage, manifest_path)
        manifest["entries"] = {
            path: entry
            for path, entry in manifest["entries"].items()
            if storage.exists(path)
        }
        manifest["entries"][insight_path] = {
            "model": model,
            "dataset_revisions": revisions,
            "prompt_sha256": prompt_hash(prompt_key),
        }
        atomic_write(
            local_manifest,
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        )
