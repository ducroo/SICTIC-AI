from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from lib.active_dataset import activate_dataset
from lib.env import get_env_var
from lib.slugify import slugify
from lib.storage import Storage, get_storage
from lib.storage_domains import (
    dataset_location_for_domain,
)


STARTUP_DATASET_SUBDIRS = (
    "data-room",
    "linkedin",
    "dealum",
    "snippets",
    "post-deal",
)


@lru_cache(maxsize=1)
def startup_aliases() -> dict[str, str]:
    path = Path(get_env_var("REPO_PATH")) / "config" / "startup_aliases.json"
    if not path.exists():
        return {}
    aliases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(aliases, dict):
        raise ValueError(f"{path}: expected an object of startup slug aliases")
    return {slugify(source): slugify(target) for source, target in aliases.items()}


def canonical_startup_slug(startup: str) -> str:
    slug = slugify(startup)
    aliases = startup_aliases()
    seen = set()
    while slug in aliases:
        if slug in seen:
            raise ValueError(f"Circular startup alias involving {slug!r}")
        seen.add(slug)
        slug = aliases[slug]
    return slug


def ensure_startup_dossier(
    startup: str,
    *,
    storage: Optional[Storage] = None,
    activate: bool = True,
) -> str:
    """Create the standard raw and parsed startup dataset layout."""
    dataset_slug = canonical_startup_slug(startup)
    storage = storage or get_storage()
    location = dataset_location_for_domain(dataset_slug, "startups")

    for root in (location.raw_rel, location.parsed_rel):
        storage.mkdir(root)
        for subdir in STARTUP_DATASET_SUBDIRS:
            storage.mkdir(f"{root}/{subdir}")

    active_marker = location.active_marker_rel
    if activate and not storage.exists(active_marker):
        activate_dataset(dataset_slug)
    return dataset_slug
