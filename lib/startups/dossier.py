"""Create the standard storage layout for a startup dossier."""

from __future__ import annotations

from typing import Optional

from lib.datasets.paths import dataset_location_for_domain
from lib.datasets.state import activate_dataset
from lib.startups.identity import canonical_startup_slug
from lib.storage import Storage, get_storage


STARTUP_DATASET_SUBDIRS = (
    "data-room",
    "linkedin",
    "dealum",
    "snippets",
    "post-deal",
)


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
