"""Build generated datasets from selected insight files."""

from __future__ import annotations

from pathlib import PurePosixPath

from lib.datasets.paths import dataset_location_for_domain
from lib.insights.file import InsightFile
from lib.logger import get_logger
from lib.slugify import slugify
from lib.storage import get_storage

logger = get_logger(__name__)


async def dataset_from_insight(
    target_dataset: str,
    source_datasets: list[str] | None,
    skill: str,
    *,
    dry_run: bool = False,
) -> list[InsightFile]:
    """Reconcile a generated dataset from preferred stored insights."""
    target_slug = slugify(target_dataset)
    if not target_slug:
        raise ValueError("target_dataset must not be empty.")

    skill_slug = slugify(skill)
    selected = InsightFile.find_all(
        skill=skill_slug,
        datasets=source_datasets,
        selection="any",
    )
    target_rel = dataset_location_for_domain(
        target_slug,
        "generated",
    ).raw_rel

    logger.info(
        "Reconciling generated dataset '%s' from %s selected '%s' "
        "insights.",
        target_slug,
        len(selected),
        skill_slug,
    )

    desired: dict[str, InsightFile] = {}
    for insight in selected:
        relative_target = str(
            PurePosixPath(insight.dataset) / insight.dataset_relative_path
        )
        if relative_target in desired:
            raise ValueError(
                f"Multiple insights map to target path {relative_target!r}."
            )
        desired[relative_target] = insight

    storage = get_storage()
    if not dry_run and not storage.exists(target_rel):
        storage.mkdir(target_rel)
    existing = (
        dict(storage.list_with_mtime(target_rel, recursive=True))
        if storage.exists(target_rel)
        else {}
    )

    copied = 0
    unchanged = 0
    for relative_target, insight in desired.items():
        destination = f"{target_rel}/{relative_target}"
        target_mtime = existing.pop(relative_target, None)
        source_mtime = storage.mtime(insight.path)
        copy_required = (
            target_mtime is None
            or source_mtime is None
            or source_mtime > target_mtime
        )
        if not copy_required:
            unchanged += 1
            logger.debug("Skipped up-to-date file %s.", destination)
            continue

        if dry_run:
            logger.info(
                "[dry-run] Would copy %s -> %s",
                insight.path,
                destination,
            )
        else:
            storage.write_bytes(destination, storage.read_bytes(insight.path))
        copied += 1

    removed = 0
    obsolete_directories = set()
    desired_paths = set(desired)
    for relative_orphan in sorted(existing):
        orphan = f"{target_rel}/{relative_orphan}"
        parent = PurePosixPath(relative_orphan).parent
        while str(parent) != ".":
            parent_text = str(parent)
            if not any(
                path.startswith(f"{parent_text}/")
                for path in desired_paths
            ):
                obsolete_directories.add(parent_text)
            parent = parent.parent
        if dry_run:
            logger.info("[dry-run] Would remove obsolete file %s", orphan)
        else:
            storage.remove(orphan)
        removed += 1

    if not dry_run:
        for relative_directory in sorted(
            obsolete_directories,
            key=lambda value: len(PurePosixPath(value).parts),
            reverse=True,
        ):
            storage.rmtree(f"{target_rel}/{relative_directory}")

    logger.info(
        "Dataset reconciliation complete: selected=%s copied=%s "
        "removed=%s unchanged=%s dry_run=%s.",
        len(selected),
        copied,
        removed,
        unchanged,
        dry_run,
    )
    return selected
