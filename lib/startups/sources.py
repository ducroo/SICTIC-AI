from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

from lib.adapters.dealum import DealumAdapter
from lib.startups.dealum import dealum_manifest_path, import_startup_from_dealum
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

    if dataset_exists and (not refresh_dealum or not _dealum_sync_due(dataset_slug)):
        return StartupDataStatus(
            startup=startup,
            dataset_slug=dataset_slug,
            dataset_exists=True,
            dealum_configured=True,
        )

    try:
        result = import_startup_from_dealum(startup, adapter=adapter)
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
    storage = get_storage()
    manifest_path = dealum_manifest_path(dataset_slug)
    if not storage.exists(manifest_path):
        return True
    try:
        ttl = int(os.environ.get("DEALUM_SYNC_TTL_SECONDS", "86400"))
    except ValueError:
        ttl = 86400
    mtime = storage.mtime(manifest_path) or 0.0
    return (time.time() - mtime) >= ttl
