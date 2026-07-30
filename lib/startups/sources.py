from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

from lib.adapters.dealum import DealumAdapter
from lib.startups.dealum import import_startup_from_dealum
from lib.startups.dealum.manifest import (
    LAST_SUCCESSFUL_PULL_AT,
    read_manifest,
)
from lib.logger import get_logger
from lib.startups.identity import canonical_startup_slug
from lib.storage import get_storage
from lib.datasets.paths import (
    find_dataset_location,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class StartupDataStatus:
    startup: str
    dataset_slug: str
    dataset_exists: bool
    dealum_configured: bool
    dealum_checked: bool = False
    dealum_imported: bool = False
    dealum_changed: bool = False
    dealum_error: Optional[str] = None


async def ensure_startup_dataset(
    startup: str,
    *,
    refresh_dealum: bool = True,
    sync_after_import: bool = True,
) -> StartupDataStatus:
    """Optionally hydrate a startup dataset from Dealum without changing no-Dealum behavior."""
    dataset_slug = canonical_startup_slug(startup)
    storage = get_storage()
    existing_location = find_dataset_location(dataset_slug)
    dataset_exists = existing_location is not None
    adapter = DealumAdapter()

    if not adapter.is_configured():
        return StartupDataStatus(
            startup=startup,
            dataset_slug=dataset_slug,
            dataset_exists=dataset_exists,
            dealum_configured=False,
        )

    if dataset_exists and (
        not refresh_dealum or not _dealum_sync_due(dataset_slug)
    ):
        return StartupDataStatus(
            startup=startup,
            dataset_slug=dataset_slug,
            dataset_exists=True,
            dealum_configured=True,
        )

    try:
        result = import_startup_from_dealum(
            startup,
            adapter=adapter,
            activate=False,
        )
        if result.imported and result.changed and sync_after_import:
            from lib.datasets.ingestion import sync_datasets

            await sync_datasets([result.dataset_slug], raise_on_error=False, force=True)
        return StartupDataStatus(
            startup=startup,
            dataset_slug=result.dataset_slug,
            dataset_exists=find_dataset_location(result.dataset_slug) is not None,
            dealum_configured=True,
            dealum_checked=True,
            dealum_imported=result.imported,
            dealum_changed=result.changed,
        )
    except Exception as e:
        logger.warning(f"[{dataset_slug}] Dealum preflight failed; continuing with existing data if available: {e}")
        return StartupDataStatus(
            startup=startup,
            dataset_slug=dataset_slug,
            dataset_exists=dataset_exists,
            dealum_configured=True,
            dealum_checked=True,
            dealum_error=str(e),
        )


def _dealum_sync_due(dataset_slug: str) -> bool:
    manifest = read_manifest(dataset_slug)
    last_successful_pull = manifest.get(LAST_SUCCESSFUL_PULL_AT)
    if not isinstance(last_successful_pull, (int, float)):
        return True
    try:
        ttl = int(os.environ.get("DEALUM_SYNC_TTL_SECONDS", "21600"))
    except ValueError:
        ttl = 21600
    return (time.time() - last_successful_pull) >= ttl
