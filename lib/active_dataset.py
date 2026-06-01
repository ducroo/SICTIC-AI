import time
from datetime import datetime, timezone
from typing import Optional
from lib.logger import get_logger
from lib.slugify import slugify
from lib.storage import get_storage
from lib.storage_domains import dataset_active_marker_path, dataset_raw_path, list_dataset_names

logger = get_logger(__name__)

ACTIVE_MARKER = "__active_dataset__"
ARCHIVED_MARKER = "__archived_dataset__"
MARKER_TEXT = """Feel free to adjust the name of this file. It only signals whether this dataset should be included in the overnight bulk refresh dependent on the name

* __active_dataset__ => do include
* __archived_dataset__ => do not include
"""
MARKER_MTIME = datetime(1999, 12, 31, tzinfo=timezone.utc).timestamp()


def dataset_archived_marker_path(dataset_name: str) -> str:
    """Returns the __archived_dataset__ marker file path for a dataset."""
    return f"{dataset_raw_path(dataset_name)}/{ARCHIVED_MARKER}"


def _write_marker(storage, marker_path: str) -> None:
    storage.write_text(marker_path, MARKER_TEXT)
    storage.set_mtime(marker_path, MARKER_MTIME)


def _set_dataset_marker(dataset_name: str, *, active: bool) -> str:
    slug = slugify(dataset_name)
    storage = get_storage()
    active_marker_path = dataset_active_marker_path(slug)
    archived_marker_path = dataset_archived_marker_path(slug)
    marker_path = active_marker_path if active else archived_marker_path

    storage.remove(active_marker_path)
    storage.remove(archived_marker_path)
    _write_marker(storage, marker_path)
    return marker_path


def is_active_dataset(dataset_name: str) -> bool:
    """Checks if a dataset has the __active_dataset__ marker file."""
    slug = slugify(dataset_name)
    return get_storage().exists(dataset_active_marker_path(slug))

def activate_dataset(dataset_name: str) -> None:
    """Switches a dataset to the __active_dataset__ marker file."""
    slug = slugify(dataset_name)
    marker_path = _set_dataset_marker(slug, active=True)
    logger.info(f"Activated dataset: {slug} (created {marker_path})")

def archive_dataset(dataset_name: Optional[str] = None, age_days: Optional[int] = None) -> None:
    """
    Archives datasets by switching from __active_dataset__ to __archived_dataset__.
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
        for item in list_dataset_names("startups") + list_dataset_names("community"):
            slug = slugify(item)
            marker_path = dataset_active_marker_path(slug)
            
            if storage.exists(marker_path):
                mtime = storage.mtime(marker_path)
                if mtime is not None:
                    # mtime could be None if the storage backend doesn't support it, but both Local and Google Drive do
                    file_age = now - mtime
                    if file_age > age_seconds:
                        _set_dataset_marker(slug, active=False)
                        logger.info(f"Archived inactive dataset '{slug}' (marker was {file_age/86400:.1f} days old).")
