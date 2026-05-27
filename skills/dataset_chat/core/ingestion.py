import asyncio
import time
from typing import List

from lib.adapters.qdrant import QdrantAdapter
from lib.adapters.docling import DoclingAdapter
from lib.env import get_env_var
from lib.storage import get_storage
from lib.logger import get_logger

from lib.slugify import slugify

logger = get_logger(__name__)

IGNORED_EXTENSIONS = (
    '.mp4', '.avi', '.mov', '.mkv', '.wmv',
    '.mp3', '.wav', '.aac', '.flac', '.m4a',
    '.zip', '.rar', '.7z', '.tar', '.gz',
    '.exe', '.bin', '.dll', '.so', '.dmg',
    '.gdoc', '.gsheet', '.gslide', '.gdraw'
)

_sync_locks = {}
_last_sync_times = {}
SYNC_CACHE_TTL = 60  # seconds

async def sync_datasets(dataset_names: List[str]):
    """Iterates over multiple datasets to sync them overnight."""
    for name in dataset_names:
        dataset_slug = slugify(name)
        
        if dataset_slug not in _sync_locks:
            _sync_locks[dataset_slug] = asyncio.Lock()
            
        async with _sync_locks[dataset_slug]:
            last_sync = _last_sync_times.get(dataset_slug, 0)
            if time.time() - last_sync < SYNC_CACHE_TTL:
                logger.debug(f"[{dataset_slug}] Skipping sync for dataset (synced recently).")
                continue

            logger.info(f"[{dataset_slug}] === Starting sync for dataset ===")
            try:
                await _sync_single_dataset(dataset_slug)
                _last_sync_times[dataset_slug] = time.time()
            except Exception as e:
                logger.error(f"[{name}] Failed to sync dataset: {e}")
            logger.info(f"[{name}] === Completed sync for dataset ===")

async def _sync_single_dataset(dataset_name: str):
    """Main orchestrator: Syncs drive to disk (OCR), then disk to DB (Embed) for a single dataset."""
    dataset_slug = slugify(dataset_name)
    storage = get_storage()
    raw_dataset_rel = f"datasets/{dataset_slug}"
    parsed_dataset_rel = f"datasets2md/{dataset_slug}"

    # Refresh storage caches (no-op for LocalStorage; invalidates Drive path cache).
    storage.refresh(raw_dataset_rel)

    if not storage.exists(raw_dataset_rel):
        raise ValueError(f"Dataset '{dataset_slug}' does not exist on drive.")

    # 1. OCR Phase: Sync original files to parsed markdown on disk
    await _sync_ocr_to_disk(dataset_slug, raw_dataset_rel, parsed_dataset_rel)

    # 2. Ingest Phase: Sync parsed markdown from disk to Qdrant
    await _sync_disk_to_qdrant(dataset_slug, raw_dataset_rel, parsed_dataset_rel)


def _list_source_files(storage, raw_rel: str):
    """Returns [(filename_relative_to_raw_rel, mtime_epoch)] for all non-ignored files."""
    items = storage.list_with_mtime(raw_rel, recursive=True)
    return [(name, mtime) for name, mtime in items if not name.lower().endswith(IGNORED_EXTENSIONS)]


async def _sync_ocr_to_disk(dataset_name: str, raw_rel: str, parsed_rel: str):
    """Compare source mtimes against parsed mtimes; run Docling on the diff and write markdown back."""
    storage = get_storage()
    source_files = _list_source_files(storage, raw_rel)

    files_to_ocr = []
    for filename, drive_mtime in source_files:
        parsed_filepath = f"{parsed_rel}/{filename}.md"
        parsed_mtime = storage.mtime(parsed_filepath) or 0.0
        if drive_mtime > parsed_mtime:
            files_to_ocr.append({
                "filename": filename,
                "mod_time": drive_mtime,
                "is_new": parsed_mtime == 0.0,
            })
        #else:
        #    logger.debug(f"[{dataset_name}] Parsed file up to date for: {filename}")

    if not files_to_ocr:
        logger.info(f"[{dataset_name}] No new files to OCR.")
        return

    logger.info(f"[{dataset_name}] Found {len(files_to_ocr)} files to OCR.")

    # Materialize each source file locally so docling can read from disk. In
    # mount mode this is a no-op (LocalStorage.local_path just returns the
    # filesystem path). In API mode this triggers a download into the cache.
    for f_data in files_to_ocr:
        f_data["local_path"] = storage.local_path(f"{raw_rel}/{f_data['filename']}")

    try:
        max_concurrent = int(get_env_var("MAX_CONCURRENT_DOCLING"))
    except Exception:
        max_concurrent = 10
    docling = DoclingAdapter(concurrency_limit=max_concurrent)

    async for filename, text in docling.extract_documents(files_to_ocr):
        if text:
            parsed_filepath = f"{parsed_rel}/{filename}.md"
            storage.write_text(parsed_filepath, text)
            logger.info(f"[{dataset_name}] Saved parsed text to {parsed_filepath}")


async def _sync_disk_to_qdrant(dataset_name: str, raw_rel: str, parsed_rel: str):
    """Embed parsed markdown into Qdrant; remove orphans whose source is gone."""
    dataset_slug = slugify(dataset_name)
    qdrant = QdrantAdapter(dataset_slug)
    storage = get_storage()

    source_files = _list_source_files(storage, raw_rel)
    current_drive_files = {name for name, _ in source_files}
    drive_mtimes = dict(source_files)

    db_mtimes = qdrant.get_document_mtimes()

    # Handle orphans
    orphans = set(db_mtimes.keys()) - current_drive_files
    for orphan in orphans:
        logger.info(f"[{dataset_slug}] File deleted from drive: {orphan}. Removing from Qdrant.")
        qdrant.delete_document(orphan)
        parsed_filepath = f"{parsed_rel}/{orphan}.md"
        if storage.exists(parsed_filepath):
            try:
                storage.remove(parsed_filepath)
            except Exception as e:
                logger.warning(f"[{dataset_name}] Failed to remove cached file {parsed_filepath}: {e}")

    # Process each file against DB
    files_to_embed = []
    for filename in current_drive_files:
        drive_mtime = drive_mtimes.get(filename, 0.0)
        db_mtime = db_mtimes.get(filename)

        if db_mtime is None or drive_mtime > db_mtime:
            parsed_filepath = f"{parsed_rel}/{filename}.md"
            if storage.exists(parsed_filepath):
                files_to_embed.append((filename, drive_mtime, parsed_filepath))
            else:
                logger.warning(f"[{dataset_name}] Parsed file missing for {filename}, skipping embedding.")

    if not files_to_embed:
        logger.info(f"[{dataset_name}] No new chunks to embed.")
        return

    logger.info(f"[{dataset_name}] Embedding and upserting {len(files_to_embed)} documents...")

    # Mini-batch / Sequential upsert for crash resilience
    for filename, mod_time, parsed_filepath in files_to_embed:
        logger.info(f"[{dataset_slug}] Embedding {filename}...")
        try:
            text = storage.read_text(parsed_filepath)
            if text.strip():
                from lib.adapters.qdrant import Chunker
                chunks = Chunker.split_markdown(text, filename, mod_time)
                await qdrant.upsert(chunks)
                logger.info(f"[{dataset_slug}] Successfully upserted {filename}.")
        except Exception as e:
            logger.error(f"[{dataset_slug}] Failed to embed and upsert {filename}: {e}")
