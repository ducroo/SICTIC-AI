"""Orchestrate source discovery, conversion, and Qdrant indexing."""

from __future__ import annotations

import asyncio
from typing import List

from lib.datasets.conversion import (
    reconcile_conversions,
)
from lib.datasets.indexing import reconcile_index
from lib.datasets.manifest import IngestionManifest
from lib.datasets.models import IngestionFailure, IngestionResult
from lib.datasets.paths import dataset_parsed_path, dataset_raw_path
from lib.datasets.source import (
    SourceDocument,
    snapshot_source_files,
)
from lib.infrastructure.logging import get_logger
from lib.slugify import slugify
from lib.storage import get_storage

logger = get_logger(__name__)

_sync_locks: dict[str, asyncio.Lock] = {}


async def sync_datasets(
    dataset_names: List[str],
    raise_on_error: bool = False,
    *,
    force: bool = False,
) -> list[IngestionResult]:
    """Reconcile source, parsed, and indexed state for multiple datasets."""
    del force  # Retained for CLI compatibility; reconciliation is state-based.
    results: list[IngestionResult] = []
    errors: list[str] = []

    for name in dataset_names:
        dataset_slug = slugify(name)
        lock = _sync_locks.setdefault(dataset_slug, asyncio.Lock())

        async with lock:
            logger.info(
                "[%s] === Starting sync for dataset ===",
                dataset_slug,
            )
            try:
                result = await _sync_single_dataset(dataset_slug)
                results.append(result)
                errors.extend(
                    (
                        f"{dataset_slug}/{failure.filename} "
                        f"({failure.stage}): {failure.error}"
                    )
                    for failure in result.failures
                )
            except Exception as error:
                logger.error(
                    "[%s] Failed to sync dataset: %s",
                    dataset_slug,
                    error,
                )
                errors.append(f"{dataset_slug}: {error}")
            logger.info(
                "[%s] === Completed sync for dataset ===",
                dataset_slug,
            )

    if errors and raise_on_error:
        raise RuntimeError("Dataset sync failed: " + "; ".join(errors))
    return results


async def _sync_single_dataset(dataset_name: str) -> IngestionResult:
    """Run all ingestion stages for one dataset under the caller's lock."""
    dataset_slug = slugify(dataset_name)
    storage = get_storage()
    raw_rel = dataset_raw_path(dataset_slug)
    parsed_rel = dataset_parsed_path(dataset_slug)
    result = IngestionResult(dataset=dataset_slug)

    storage.refresh(raw_rel)
    if not storage.exists(raw_rel):
        raise ValueError(
            f"Dataset '{dataset_slug}' does not exist in storage at "
            f"'{raw_rel}'."
        )

    sources = snapshot_source_files(storage, raw_rel)
    manifest = IngestionManifest.load(storage, parsed_rel)
    await reconcile_conversions(
        dataset_slug,
        raw_rel,
        parsed_rel,
        sources=sources,
        manifest=manifest,
        result=result,
    )
    await reconcile_index(
        dataset_slug,
        raw_rel,
        parsed_rel,
        sources=sources,
        manifest=manifest,
        result=result,
    )
    return result


__all__ = [
    "IngestionFailure",
    "IngestionResult",
    "SourceDocument",
    "sync_datasets",
]
