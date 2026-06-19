"""Build generated datasets from selected insight files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from lib.datasets.paths import dataset_location_for_domain
from lib.insights.discovery import StoredInsight, discover_insights
from lib.insights.file import InsightFile
from lib.logger import get_logger
from lib.slugify import slugify
from lib.storage import get_storage

logger = get_logger(__name__)


@dataclass(frozen=True)
class InsightHydrationResult:
    target_dataset: str
    target_path: str
    insight: str
    source_dataset: str | None
    candidates: int = 0
    entities: int = 0
    selected: int = 0
    synced: int = 0
    removed: int = 0
    unchanged: int = 0
    dry_run: bool = False


async def hydrate_dataset_from_insights(
    insight_name: str,
    source_dataset: str | None = None,
    *,
    dry_run: bool = False,
) -> InsightHydrationResult:
    """Hydrate a generated dataset from preferred stored insight versions."""
    insight_slug = slugify(insight_name)
    if source_dataset:
        target_slug = slugify(f"{source_dataset}-{insight_slug}")
    else:
        target_slug = slugify(f"active-{insight_slug}")
    target_rel = dataset_location_for_domain(
        target_slug,
        "generated",
    ).raw_rel

    logger.info(
        "Hydrating dataset '%s' from insight '%s'...",
        target_slug,
        insight_slug,
    )

    storage = get_storage()
    if not storage.exists(target_rel):
        storage.mkdir(target_rel)
        existing_files = {}
    else:
        existing_files = {
            PurePosixPath(name).name: mtime
            for name, mtime in storage.list_with_mtime(target_rel)
        }

    candidates = discover_insights(
        insight_slug,
        source_dataset=source_dataset,
        exclude_dataset=target_slug,
    )
    if not candidates:
        logger.warning(
            "No files matching insight '%s' found in specified sources.",
            insight_slug,
        )
        return InsightHydrationResult(
            target_dataset=target_slug,
            target_path=target_rel,
            insight=insight_slug,
            source_dataset=source_dataset,
            dry_run=dry_run,
        )

    logger.info(
        "Found %s insight files to evaluate for syncing.",
        len(candidates),
    )
    candidates_by_path = {candidate.path: candidate for candidate in candidates}
    entity_to_candidates: dict[str, list[StoredInsight]] = {}
    for candidate in candidates:
        entity_to_candidates.setdefault(
            candidate.identifier,
            [],
        ).append(candidate)

    selected_count = 0
    sync_count = 0
    unchanged_count = 0
    for identifier, entity_candidates in entity_to_candidates.items():
        sample = entity_candidates[0]
        selected = InsightFile(
            dataset=sample.dataset,
            skill=insight_slug,
            model="manual",
            identifier=identifier,
            subdir=sample.subdir,
        ).find_any()
        if selected is None or selected.path not in candidates_by_path:
            continue
        selected_count += 1

        candidate = candidates_by_path[selected.path]
        target_file_rel = f"{target_rel}/{selected.filename}"
        if selected.filename in existing_files:
            target_mtime = existing_files.pop(selected.filename)
            if target_mtime >= candidate.mtime - 1.0:
                logger.debug(
                    "Skipped %s (unchanged/up-to-date)",
                    selected.filename,
                )
                unchanged_count += 1
                continue

        try:
            if dry_run:
                logger.info(
                    "[dry-run] Would sync %s -> %s",
                    selected.path,
                    target_file_rel,
                )
            else:
                storage.write_bytes(
                    target_file_rel,
                    storage.read_bytes(selected.path),
                )
            logger.debug(
                "Synced %s -> %s",
                selected.path,
                target_file_rel,
            )
            sync_count += 1
        except Exception as error:
            logger.error("Failed to sync %s: %s", selected.path, error)

    orphan_count = 0
    for orphan in list(existing_files):
        orphan_rel = f"{target_rel}/{orphan}"
        try:
            if dry_run:
                logger.info(
                    "[dry-run] Would remove orphaned file %s",
                    orphan_rel,
                )
            else:
                storage.remove(orphan_rel)
            orphan_count += 1
        except Exception as error:
            logger.warning(
                "Failed to remove orphaned file %s: %s",
                orphan,
                error,
            )

    logger.info(
        "Dataset hydration complete. %s files synced, %s removed, "
        "%s unchanged.",
        sync_count,
        orphan_count,
        unchanged_count,
    )
    return InsightHydrationResult(
        target_dataset=target_slug,
        target_path=target_rel,
        insight=insight_slug,
        source_dataset=source_dataset,
        candidates=len(candidates),
        entities=len(entity_to_candidates),
        selected=selected_count,
        synced=sync_count,
        removed=orphan_count,
        unchanged=unchanged_count,
        dry_run=dry_run,
    )


# Compatibility names for existing Python callers.
DatasetFromInsightResult = InsightHydrationResult
dataset_from_insight = hydrate_dataset_from_insights
