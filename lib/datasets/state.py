import calendar
import time
from datetime import datetime, timezone
from typing import Optional

from lib.infrastructure.logging import get_logger
from lib.slugify import slugify
from lib.storage import get_storage
from lib.datasets.paths import (
    dataset_active_marker_path,
    dataset_raw_path,
    list_all_dataset_names,
)
from lib.datasets.source import IGNORED_FILENAMES

logger = get_logger(__name__)

ACTIVE_MARKER = "__active_dataset__.md"
ARCHIVED_MARKER = "__archived_dataset__.md"
MARKER_TEXT = """# Dataset Refresh Status

This marker controls whether the dataset is included in automated bulk refreshes.

- `__active_dataset__.md`: include the dataset.
- `__archived_dataset__.md`: exclude the dataset.

Rename this file to the other marker name to change the dataset's refresh status.
"""


def dataset_archived_marker_path(dataset_name: str) -> str:
    """Returns the archived dataset marker file path for a dataset."""
    return f"{dataset_raw_path(dataset_name)}/{ARCHIVED_MARKER}"


def _write_marker(storage, marker_path: str) -> None:
    storage.write_text(marker_path, MARKER_TEXT)


def _set_dataset_marker(dataset_name: str, *, active: bool) -> str:
    slug = slugify(dataset_name)
    storage = get_storage()
    active_marker_path = dataset_active_marker_path(slug)
    archived_marker_path = dataset_archived_marker_path(slug)
    marker_path = active_marker_path if active else archived_marker_path
    other_marker_path = archived_marker_path if active else active_marker_path

    storage.remove(other_marker_path)
    if not storage.exists(marker_path):
        _write_marker(storage, marker_path)
    return marker_path


def is_active_dataset(dataset_name: str) -> bool:
    """Checks if a dataset has the active dataset marker file."""
    slug = slugify(dataset_name)
    return get_storage().exists(dataset_active_marker_path(slug))


def is_archived_dataset(dataset_name: str) -> bool:
    """An archived marker prevents automatic reactivation, regardless of stage."""
    return get_storage().exists(dataset_archived_marker_path(dataset_name))

def activate_dataset(dataset_name: str) -> None:
    """Switches a dataset to the active dataset marker file."""
    slug = slugify(dataset_name)
    marker_path = _set_dataset_marker(slug, active=True)
    logger.info(f"Activated dataset: {slug} (created {marker_path})")


def latest_dataset_edit(dataset_name: str) -> float | None:
    """Latest source-file edit, including the active marker but not bookkeeping.

    Unlike ingestion, activity includes non-ingestible documents (e.g. images).
    Parsed files and insights live outside the raw dataset directory.
    """
    storage = get_storage()
    ignored = IGNORED_FILENAMES - {ACTIVE_MARKER}
    edits = [
        mtime
        for name, mtime in storage.list_with_mtime(dataset_raw_path(dataset_name), recursive=True)
        if name.rsplit("/", 1)[-1] not in ignored
        and not any(part.startswith(".") for part in name.split("/"))
    ]
    return max(edits, default=None)


def update_dataset_inactivity(dataset_name: str, *, months: int, now: float | None = None) -> None:
    """Expire inactive datasets without ever automatically reactivating an archive."""
    if is_archived_dataset(dataset_name):
        archive_dataset(dataset_name)
        return
    now = time.time() if now is None else now
    today = datetime.fromtimestamp(now, timezone.utc)
    month_index = today.year * 12 + today.month - 1 - months
    year, month = divmod(month_index, 12)
    month += 1
    cutoff = today.replace(
        year=year, month=month,
        day=min(today.day, calendar.monthrange(year, month)[1]),
    ).timestamp()
    latest = latest_dataset_edit(dataset_name)
    if is_active_dataset(dataset_name):
        if latest is None or latest <= cutoff:
            archive_dataset(dataset_name)
        return
    archive_dataset(dataset_name)


def archive_dataset(dataset_name: Optional[str] = None, age_days: Optional[int] = None) -> None:
    """
    Archives datasets by switching from the active marker to the archived marker.
    - If dataset_name is provided, archives just that dataset.
    - If age_days is provided, archives datasets whose marker file is older than age_days.
    """
    storage = get_storage()
    now = time.time()
    
    if dataset_name:
        slug = slugify(dataset_name)
        marker_path = _set_dataset_marker(slug, active=False)
        logger.info(f"Archived dataset: {slug} (created {marker_path})")
            
    if age_days is not None:
        age_seconds = age_days * 86400
        for item in list_all_dataset_names(("startups", "community")):
            slug = slugify(item)
            marker_path = dataset_active_marker_path(slug)
            
            if storage.exists(marker_path):
                mtime = storage.mtime(marker_path)
                if mtime is not None:
                    # mtime may be unavailable for a future storage backend.
                    file_age = now - mtime
                    if file_age > age_seconds:
                        _set_dataset_marker(slug, active=False)
                        logger.info(f"Archived inactive dataset '{slug}' (marker was {file_age/86400:.1f} days old).")
