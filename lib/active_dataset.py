import time
from typing import Optional
from lib.logger import get_logger
from lib.slugify import slugify
from lib.storage import get_storage

logger = get_logger(__name__)

def is_active_dataset(dataset_name: str) -> bool:
    """Checks if a dataset has the __active_dataset__ marker file."""
    slug = slugify(dataset_name)
    return get_storage().exists(f"datasets/{slug}/__active_dataset__")

def activate_dataset(dataset_name: str) -> None:
    """Adds the __active_dataset__ marker file to a dataset."""
    slug = slugify(dataset_name)
    marker_path = f"datasets/{slug}/__active_dataset__"
    storage = get_storage()
    if not storage.exists(marker_path):
        storage.write_text(marker_path, "")
        logger.info(f"Activated dataset: {slug} (created {marker_path})")
    else:
        logger.debug(f"Dataset {slug} is already active.")

def archive_dataset(dataset_name: Optional[str] = None, age_days: Optional[int] = None) -> None:
    """
    Archives datasets by removing their __active_dataset__ marker.
    - If dataset_name is provided, archives just that dataset.
    - If age_days is provided, archives datasets whose marker file is older than age_days.
    """
    storage = get_storage()
    now = time.time()
    
    if dataset_name:
        slug = slugify(dataset_name)
        marker_path = f"datasets/{slug}/__active_dataset__"
        if storage.exists(marker_path):
            storage.remove(marker_path)
            logger.info(f"Archived dataset: {slug}")
        else:
            logger.debug(f"Dataset {slug} is already inactive (no marker found).")
            
    if age_days is not None:
        age_seconds = age_days * 86400
        if not storage.exists("datasets"):
            return
            
        for item in storage.list("datasets"):
            if not storage.is_dir(f"datasets/{item}"):
                continue
            
            slug = slugify(item)
            marker_path = f"datasets/{slug}/__active_dataset__"
            
            if storage.exists(marker_path):
                mtime = storage.mtime(marker_path)
                if mtime is not None:
                    # mtime could be None if the storage backend doesn't support it, but both Local and Google Drive do
                    file_age = now - mtime
                    if file_age > age_seconds:
                        storage.remove(marker_path)
                        logger.info(f"Archived inactive dataset '{slug}' (marker was {file_age/86400:.1f} days old).")
