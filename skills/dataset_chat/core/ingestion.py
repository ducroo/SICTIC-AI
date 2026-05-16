import os
import asyncio
import time
from datetime import datetime
from typing import List

from lib.adapters.qdrant import QdrantAdapter
from lib.adapters.docling import DoclingAdapter
from lib.adapters.rclone import RcloneAdapter
from lib.env import get_env_var
from lib.logger import get_logger

logger = get_logger(__name__)

IGNORED_EXTENSIONS = (
    '.mp4', '.avi', '.mov', '.mkv', '.wmv',
    '.mp3', '.wav', '.aac', '.flac', '.m4a',
    '.zip', '.rar', '.7z', '.tar', '.gz',
    '.exe', '.bin', '.dll', '.so', '.dmg'
)

_sync_locks = {}
_last_sync_times = {}
SYNC_CACHE_TTL = 60  # seconds

async def sync_datasets(dataset_names: List[str]):
    """Iterates over multiple datasets to sync them overnight."""
    for name in dataset_names:
        dataset_key = name.lower()
        
        if dataset_key not in _sync_locks:
            _sync_locks[dataset_key] = asyncio.Lock()
            
        async with _sync_locks[dataset_key]:
            last_sync = _last_sync_times.get(dataset_key, 0)
            if time.time() - last_sync < SYNC_CACHE_TTL:
                logger.debug(f"[{name}] Skipping sync for dataset (synced recently).")
                continue

            logger.info(f"[{name}] === Starting sync for dataset ===")
            try:
                await _sync_single_dataset(name)
                _last_sync_times[dataset_key] = time.time()
            except Exception as e:
                logger.error(f"[{name}] Failed to sync dataset: {e}")
            logger.info(f"[{name}] === Completed sync for dataset ===")

async def _sync_single_dataset(dataset_name: str):
    """Main orchestrator: Syncs drive to disk (OCR), then disk to DB (Embed) for a single dataset."""
    dataset_name = dataset_name.lower()
    gdrive_mount = get_env_var("GDRIVE_MOUNT")
    oc_base_path = os.path.join(gdrive_mount, "datasets", dataset_name)
    parsed_base_path = os.path.join(gdrive_mount, "datasets_parsed", dataset_name)
    docling_base_path = f"/data/datasets/{dataset_name}"

    if not os.path.exists(oc_base_path):
         raise ValueError(f"Dataset '{dataset_name}' does not exist on drive.")

    os.makedirs(parsed_base_path, exist_ok=True)

    # 1. OCR Phase: Sync original files to parsed markdown on disk
    await _sync_ocr_to_disk(dataset_name, oc_base_path, parsed_base_path, docling_base_path)
    
    # 2. Ingest Phase: Sync parsed markdown from disk to Qdrant
    await _sync_disk_to_qdrant(dataset_name, oc_base_path, parsed_base_path)

async def _sync_ocr_to_disk(dataset_name: str, oc_base_path: str, parsed_base_path: str, docling_base_path: str):
    """Checks Drive vs Parsed Disk. Runs Docling for missing/outdated files and saves to disk."""
    rclone = RcloneAdapter()
    dataset_path = f"datasets/{dataset_name}"
    # this refresh is expensive, but necessary if we want to OCR them, so we have everything locally
    rclone.refresh_vfs(dataset_path)
    files = rclone.list_files(dataset_path)
    files = [f for f in files if not f["Name"].lower().endswith(IGNORED_EXTENSIONS)]

    files_to_ocr = []

    for f_info in files:
        filename = f_info["Name"]
        
        mod_time_str = f_info.get("ModTime", "")
        try:
             drive_mtime = datetime.fromisoformat(mod_time_str.replace("Z", "+00:00")).timestamp() if mod_time_str else os.path.getmtime(os.path.join(oc_base_path, filename))
        except Exception as e:
             logger.debug(f"[{dataset_name}] Failed to parse mod_time for {filename}: {e}")
             drive_mtime = 0.0

        parsed_filepath = os.path.join(parsed_base_path, filename + ".md")
        parsed_mtime = os.path.getmtime(parsed_filepath) if os.path.exists(parsed_filepath) else 0.0

        if drive_mtime > parsed_mtime:
            files_to_ocr.append({
                "filename": filename,
                "mod_time": drive_mtime,
                "is_new": parsed_mtime == 0.0
            })
        else:
            logger.debug(f"[{dataset_name}] Parsed file up to date for: {filename}")

    if not files_to_ocr:
        logger.info(f"[{dataset_name}] No new files to OCR.")
        return

    logger.info(f"[{dataset_name}] Found {len(files_to_ocr)} files to OCR.")

    try:
        max_concurrent = int(get_env_var("MAX_CONCURRENT_DOCLING"))
    except Exception:
        max_concurrent = 10
    docling = DoclingAdapter(concurrency_limit=max_concurrent)
    
    async def run_ocr_and_save():
        async for filename, text in docling.extract_documents(files_to_ocr, oc_base_path, docling_base_path):
            if text:
                parsed_filepath = os.path.join(parsed_base_path, filename + ".md")
                os.makedirs(os.path.dirname(parsed_filepath), exist_ok=True)
                with open(parsed_filepath, "w", encoding="utf-8") as f:
                    f.write(text)
                logger.info(f"[{dataset_name}] Saved parsed text to {parsed_filepath}")

    await run_ocr_and_save()

async def _sync_disk_to_qdrant(dataset_name: str, oc_base_path: str, parsed_base_path: str):
    """Checks Drive/Parsed Disk vs Qdrant. Embeds and upserts outdated files sequentially."""
    qdrant = QdrantAdapter(dataset_name)
    rclone = RcloneAdapter()
    
    dataset_path = f"datasets/{dataset_name}"
    files = rclone.list_files(dataset_path)
    files = [f for f in files if not f["Name"].lower().endswith(IGNORED_EXTENSIONS)]
    current_drive_files = {f["Name"] for f in files}
    drive_mtimes = {}
    
    for f_info in files:
        filename = f_info["Name"]
        mod_time_str = f_info.get("ModTime", "")
        try:
             drive_mtimes[filename] = datetime.fromisoformat(mod_time_str.replace("Z", "+00:00")).timestamp() if mod_time_str else os.path.getmtime(os.path.join(oc_base_path, filename))
        except Exception:
             drive_mtimes[filename] = 0.0

    db_mtimes = qdrant.get_all_document_mtimes()

    # Handle orphans
    orphans = set(db_mtimes.keys()) - current_drive_files
    for orphan in orphans:
        logger.info(f"[{dataset_name}] File deleted from drive: {orphan}. Removing from Qdrant.")
        qdrant.delete_document_points(orphan)
        parsed_filepath = os.path.join(parsed_base_path, orphan + ".md")
        if os.path.exists(parsed_filepath):
            try:
                os.remove(parsed_filepath)
            except OSError as e:
                logger.warning(f"[{dataset_name}] Failed to remove cached file {parsed_filepath}: {e}")

    # Process each file against DB
    files_to_embed = []
    for filename in current_drive_files:
        drive_mtime = drive_mtimes.get(filename, 0.0)
        db_mtime = db_mtimes.get(filename)
        
        if db_mtime is None or drive_mtime > db_mtime:
            parsed_filepath = os.path.join(parsed_base_path, filename + ".md")
            if os.path.exists(parsed_filepath):
                files_to_embed.append((filename, drive_mtime, parsed_filepath))
            else:
                logger.warning(f"[{dataset_name}] Parsed file missing for {filename}, skipping embedding.")

    if not files_to_embed:
        logger.info(f"[{dataset_name}] No new chunks to embed.")
        return

    logger.info(f"[{dataset_name}] Embedding and upserting {len(files_to_embed)} documents...")

    # Mini-batch / Sequential upsert for crash resilience
    for filename, mod_time, parsed_filepath in files_to_embed:
        logger.info(f"[{dataset_name}] Embedding {filename}...")
        try:
            with open(parsed_filepath, "r", encoding="utf-8") as f:
                text = f.read()
            
            if text.strip():
                await qdrant.ingest_documents_batch({filename: text}, {filename: mod_time})
                logger.info(f"[{dataset_name}] Successfully upserted {filename}.")
        except Exception as e:
            logger.error(f"[{dataset_name}] Failed to embed and upsert {filename}: {e}")
