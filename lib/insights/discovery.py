"""Internal discovery of stored insight-file versions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from lib.datasets.paths import dataset_location, list_all_dataset_names
from lib.slugify import slugify
from lib.storage import get_storage


@dataclass(frozen=True)
class InsightCandidate:
    path: str
    relative_path: str
    filename: str
    mtime: float
    dataset: str
    skill: str
    subdir: bool
    parent: str
    extension: str


def discover_insights(
    skill: str,
    *,
    datasets: list[str] | None,
) -> list[InsightCandidate]:
    """Enumerate physical versions of one insight across source datasets."""
    storage = get_storage()
    skill_slug = slugify(skill)
    dataset_slugs = (
        sorted({slugify(dataset) for dataset in datasets})
        if datasets is not None
        else list_all_dataset_names(("startups", "community"))
    )

    records = []
    for dataset_slug in dataset_slugs:
        location = dataset_location(dataset_slug)
        if location.domain not in {"startups", "community"}:
            raise ValueError(
                "Insight discovery only accepts startup and community "
                f"source datasets, got {dataset_slug!r}."
            )
        if not storage.exists(location.insights_rel):
            continue

        for name, mtime in storage.list_with_mtime(
            location.insights_rel,
            recursive=True,
        ):
            parts = PurePosixPath(name).parts
            if not parts:
                continue

            filename = parts[-1]
            suffix = PurePosixPath(filename).suffix
            extension = suffix.removeprefix(".").lower()
            if not extension or not extension.isalnum():
                continue

            root_file = (
                len(parts) == 1
                and filename.startswith(f"{skill_slug}-")
            )
            skill_subfolder = len(parts) > 1 and parts[0] == skill_slug
            if not root_file and not skill_subfolder:
                continue

            parent = str(PurePosixPath(*parts[:-1]))
            relative_path = f"insights/{name}"
            records.append(
                InsightCandidate(
                    path=f"{location.insights_rel}/{name}",
                    relative_path=relative_path,
                    filename=filename,
                    mtime=mtime,
                    dataset=dataset_slug,
                    skill=skill_slug,
                    subdir=skill_subfolder,
                    parent=parent,
                    extension=extension,
                )
            )

    return records
