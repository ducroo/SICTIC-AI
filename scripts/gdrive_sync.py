"""
Cleanly mirror files between STORAGE_MIRROR_PATH and Google Drive.

  pull [path]: Drive -> local. Drive is source of truth.
  push [path]: local -> Drive. Local mirror is source of truth.

The optional path is a relative subtree or file path under the configured root.
The destination is made to match the source for that path: missing files are
created, changed files are overwritten, source mtimes are preserved on the
destination, and destination-only files are deleted.

Usage:
    python scripts/gdrive_sync.py pull
    python scripts/gdrive_sync.py pull storage/startups/avientus/insights
    python scripts/gdrive_sync.py push storage/startups/avientus/insights
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lib.env  # noqa: F401  triggers .env load
from lib.env import get_env_var
from lib.logger import get_logger
from lib.storage import LocalStorage, _validate_rel
from lib.storage_gdrive import GoogleDriveStorage

logger = get_logger(__name__)
_console = logging.StreamHandler(sys.stdout)
_console.setLevel(logging.INFO)
_console.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(_console)


_SKIP_FOLDER_NAMES = {"_archive_md"}
_MTIME_TOLERANCE_SECONDS = 1.0


def _clean_rel(rel: Optional[str]) -> str:
    if not rel:
        return ""
    if rel in {".", "/"}:
        return ""
    if rel.startswith("/"):
        return _validate_rel(rel)
    rel = rel.strip("/")
    return _validate_rel(rel)


def _build_drive_storage(root_folder_id: str, credentials: str, token: str) -> GoogleDriveStorage:
    return GoogleDriveStorage(
        credentials_path=credentials,
        token_path=token,
        root_folder_id=root_folder_id,
    )


def _walk_drive(drive: GoogleDriveStorage, rel: str = "") -> List[Tuple[str, float]]:
    """Recursive list of Drive files under rel, with paths relative to root."""
    rel = _clean_rel(rel)
    drive._resolve_root_folder()
    if rel and drive.exists(rel) and not drive.is_dir(rel):
        return [(rel, drive.mtime(rel) or 0.0)]

    out: List[Tuple[str, float]] = []
    service = drive._ensure_service()
    parent_id = drive._resolve(rel) if rel else drive.root_folder_id
    if parent_id is None:
        return out

    stack: List[Tuple[str, str]] = [(parent_id, rel)]
    from googleapiclient.errors import HttpError

    while stack:
        pid, prefix = stack.pop()
        page_token = None
        while True:
            try:
                res = service.files().list(
                    q=f"'{pid}' in parents and trashed=false",
                    fields="nextPageToken,files(id,name,mimeType,modifiedTime)",
                    pageSize=1000,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                ).execute()
            except HttpError as e:
                logger.error(f"list error under {prefix!r}: {e}")
                break
            for item in res.get("files", []):
                child_rel = f"{prefix}/{item['name']}" if prefix else item["name"]
                if item.get("mimeType") == "application/vnd.google-apps.folder":
                    if item["name"] in _SKIP_FOLDER_NAMES:
                        continue
                    stack.append((item["id"], child_rel))
                    continue

                from lib.storage_gdrive import _parse_modtime

                out.append((child_rel, _parse_modtime(item.get("modifiedTime"))))
                drive._path_to_id[child_rel] = item["id"]
                drive._path_to_mime[child_rel] = item.get("mimeType", "")
            page_token = res.get("nextPageToken")
            if not page_token:
                break
    return out


def _walk_local(local: LocalStorage, rel: str = "") -> List[Tuple[str, float]]:
    """Recursive list of local files under rel, with paths relative to root."""
    rel = _clean_rel(rel)
    base = Path(local.base) / rel if rel else Path(local.base)
    if base.is_file():
        return [(rel, base.stat().st_mtime)]
    if not base.is_dir():
        return []

    out: List[Tuple[str, float]] = []
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        if any(part in _SKIP_FOLDER_NAMES for part in p.relative_to(local.base).parts):
            continue
        out.append((str(p.relative_to(local.base).as_posix()), p.stat().st_mtime))
    return out


def _same_mtime(a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= _MTIME_TOLERANCE_SECONDS


def _remove_empty_parents(base: Path, rel: str) -> None:
    parent = (base / rel).parent
    while parent != base and parent.exists():
        try:
            parent.rmdir()
        except OSError:
            return
        parent = parent.parent


def _pull_file(drive: GoogleDriveStorage, mirror: LocalStorage, rel: str, source_mtime: float) -> bool:
    if mirror.exists(rel) and _same_mtime(mirror.mtime(rel), source_mtime):
        logger.info(f"  unchanged {rel}")
        return False
    content = drive.read_bytes(rel)
    mirror.write_bytes(rel, content)
    mirror.set_mtime(rel, source_mtime)
    logger.info(f"  pull {rel} ({len(content)} bytes)")
    return True


def _push_file(mirror: LocalStorage, drive: GoogleDriveStorage, rel: str, source_mtime: float) -> bool:
    if drive.exists(rel) and _same_mtime(drive.mtime(rel), source_mtime):
        logger.info(f"  unchanged {rel}")
        return False
    content = mirror.read_bytes(rel)
    drive.write_bytes(rel, content)
    drive.set_mtime(rel, source_mtime)
    logger.info(f"  push {rel} ({len(content)} bytes)")
    return True


def _build_sync_context(
    *,
    mirror_path: Optional[str],
    root_folder_id: Optional[str],
    credentials: Optional[str],
    token: Optional[str],
) -> Tuple[LocalStorage, GoogleDriveStorage]:
    mirror_path = mirror_path or os.environ.get("STORAGE_MIRROR_PATH")
    root_folder_id = root_folder_id or os.environ.get("STORAGE_PATH") or get_env_var("STORAGE_PATH")
    credentials = (
        credentials
        or os.environ.get("GDRIVE_CREDENTIALS")
        or os.path.expanduser("~/.openclaw/gdrive-ops-credentials.json")
    )
    token = (
        token
        or os.environ.get("GDRIVE_TOKEN")
        or os.path.expanduser("~/.openclaw/gdrive-ops-token.json")
    )

    if not mirror_path:
        raise ValueError("STORAGE_MIRROR_PATH is not set and --mirror-path not given.")
    if not mirror_path.startswith("/"):
        raise ValueError(f"mirror path must be absolute, got: {mirror_path}")
    os.makedirs(mirror_path, exist_ok=True)

    return (
        LocalStorage(mirror_path),
        _build_drive_storage(root_folder_id, credentials, token),
    )


def pull_mirror(
    rel: Optional[str] = None,
    *,
    mirror_path: Optional[str] = None,
    root_folder_id: Optional[str] = None,
    credentials: Optional[str] = None,
    token: Optional[str] = None,
) -> int:
    """Make local mirror match Drive under rel."""
    rel = _clean_rel(rel)
    try:
        mirror, drive = _build_sync_context(
            mirror_path=mirror_path,
            root_folder_id=root_folder_id,
            credentials=credentials,
            token=token,
        )
    except Exception as e:
        logger.error(str(e))
        return 2

    logger.info(f"=== PULL path={rel or '.'} (drive -> local {mirror.base}) ===")
    drive_files = dict(_walk_drive(drive, rel))
    local_files = dict(_walk_local(mirror, rel))
    logger.info(f"  source_files={len(drive_files)} destination_files={len(local_files)}")

    synced = 0
    failed = 0
    pruned = 0

    for path, mtime in sorted(drive_files.items()):
        try:
            if _pull_file(drive, mirror, path, mtime):
                synced += 1
        except Exception as e:
            logger.error(f"  FAILED pull {path}: {e}")
            failed += 1

    for path in sorted(set(local_files) - set(drive_files)):
        try:
            mirror.remove(path)
            _remove_empty_parents(Path(mirror.base), path)
            logger.info(f"  prune local {path}")
            pruned += 1
        except Exception as e:
            logger.error(f"  FAILED prune local {path}: {e}")
            failed += 1

    logger.info(f"=== TOTAL synced={synced} failed={failed} pruned={pruned} ===")
    return 0 if failed == 0 else 1


def push_mirror(
    rel: Optional[str] = None,
    *,
    mirror_path: Optional[str] = None,
    root_folder_id: Optional[str] = None,
    credentials: Optional[str] = None,
    token: Optional[str] = None,
) -> int:
    """Make Drive match local mirror under rel."""
    rel = _clean_rel(rel)
    try:
        mirror, drive = _build_sync_context(
            mirror_path=mirror_path,
            root_folder_id=root_folder_id,
            credentials=credentials,
            token=token,
        )
    except Exception as e:
        logger.error(str(e))
        return 2

    logger.info(f"=== PUSH path={rel or '.'} (local {mirror.base} -> drive) ===")
    local_files = dict(_walk_local(mirror, rel))
    drive_files = dict(_walk_drive(drive, rel))
    logger.info(f"  source_files={len(local_files)} destination_files={len(drive_files)}")

    synced = 0
    failed = 0
    pruned = 0

    for path, mtime in sorted(local_files.items()):
        try:
            if _push_file(mirror, drive, path, mtime):
                synced += 1
        except Exception as e:
            logger.error(f"  FAILED push {path}: {e}")
            failed += 1

    for path in sorted(set(drive_files) - set(local_files)):
        try:
            drive.remove(path)
            logger.info(f"  prune drive {path}")
            pruned += 1
        except Exception as e:
            logger.error(f"  FAILED prune drive {path}: {e}")
            failed += 1

    logger.info(f"=== TOTAL synced={synced} failed={failed} pruned={pruned} ===")
    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("direction", choices=["pull", "push"], help="Sync direction.")
    parser.add_argument(
        "path",
        nargs="?",
        default="",
        help="Optional relative path under the configured storage root.",
    )
    parser.add_argument(
        "--mirror-path",
        default=os.environ.get("STORAGE_MIRROR_PATH"),
        help="Local mirror path (default: $STORAGE_MIRROR_PATH).",
    )
    parser.add_argument(
        "--root-folder-id",
        default=os.environ.get("STORAGE_PATH"),
        help="Drive root folder ID/path (default: $STORAGE_PATH).",
    )
    parser.add_argument(
        "--credentials",
        default=os.environ.get("GDRIVE_CREDENTIALS")
        or os.path.expanduser("~/.openclaw/gdrive-ops-credentials.json"),
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("GDRIVE_TOKEN")
        or os.path.expanduser("~/.openclaw/gdrive-ops-token.json"),
    )
    args = parser.parse_args()

    if args.direction == "pull":
        return pull_mirror(
            args.path,
            mirror_path=args.mirror_path,
            root_folder_id=args.root_folder_id,
            credentials=args.credentials,
            token=args.token,
        )
    return push_mirror(
        args.path,
        mirror_path=args.mirror_path,
        root_folder_id=args.root_folder_id,
        credentials=args.credentials,
        token=args.token,
    )


if __name__ == "__main__":
    sys.exit(main())
