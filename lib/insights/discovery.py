"""Discover stored insight files without exposing storage-layout parsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from lib.datasets.paths import (
    dataset_insights_path,
    storage_domain_config,
)
from lib.datasets.state import is_active_dataset
from lib.insights.naming import insight_base_name
from lib.slugify import slugify
from lib.storage import get_storage


@dataclass(frozen=True)
class StoredInsight:
    path: str
    filename: str
    mtime: float
    dataset: str
    skill: str
    identifier: str
    subdir: bool


def discover_insights(
    skill: str,
    *,
    source_dataset: str | None = None,
    exclude_dataset: str | None = None,
) -> list[StoredInsight]:
    """Enumerate insight files matching one skill and optional dataset."""
    storage = get_storage()
    skill_slug = slugify(skill)
    source_slug = slugify(source_dataset) if source_dataset else None
    excluded_slug = slugify(exclude_dataset) if exclude_dataset else None

    if source_slug:
        scan_roots = [(dataset_insights_path(source_slug), source_slug, True)]
    else:
        config = storage_domain_config()
        scan_roots = [
            (config["domains"][domain]["insights_root"].strip("/"), "", False)
            for domain in ("startups", "community")
            if domain in config["domains"]
        ]

    records = []
    for scan_root, fixed_dataset, root_is_insights_dir in dict.fromkeys(
        scan_roots
    ):
        if not storage.exists(scan_root):
            continue
        for name, mtime in storage.list_with_mtime(
            scan_root,
            recursive=True,
        ):
            if not name.endswith(".md"):
                continue

            parts = PurePosixPath(name).parts
            if root_is_insights_dir:
                dataset_slug = fixed_dataset
                insight_parts = parts
            else:
                if len(parts) < 3 or parts[1] != "insights":
                    continue
                dataset_slug = parts[0]
                insight_parts = parts[2:]

            if not source_slug:
                if dataset_slug == excluded_slug:
                    continue
                if not is_active_dataset(dataset_slug):
                    continue

            filename = insight_parts[-1]
            subdir = (
                len(insight_parts) > 1
                and insight_parts[-2] == skill_slug
            )
            root_file = (
                len(insight_parts) == 1
                and filename.startswith(f"{skill_slug}-")
            )
            if not subdir and not root_file:
                continue

            candidate_name = (
                filename[len(skill_slug) + 1 :]
                if root_file
                else filename
            )
            identifier = insight_base_name(candidate_name)
            if not identifier:
                continue
            records.append(
                StoredInsight(
                    path=f"{scan_root}/{name}",
                    filename=filename,
                    mtime=mtime,
                    dataset=dataset_slug,
                    skill=skill_slug,
                    identifier=identifier,
                    subdir=subdir,
                )
            )

    return records
