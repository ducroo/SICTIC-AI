"""
Pull or push subtrees between the local mirror (STORAGE_MIRROR_DIR) and
Google Drive folders listed in config/sync.yaml.

  pull: Drive -> local. Overwrites local copies. Source of truth = Drive.
  push: local -> Drive. Overwrites gdoc contents in place (file IDs preserved).
        Creates folders/files on Drive that don't yet exist there.
        Source of truth = local mirror.

No three-way merge: whichever direction you run wins. Use --dry-run to preview.
--prune deletes destination-side files/folders that aren't in the source.

Usage:
    python scripts/gdrive_sync.py pull
    python scripts/gdrive_sync.py pull --target insights --dry-run
    python scripts/gdrive_sync.py push --prune
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lib.env  # noqa: F401  triggers .env load
from lib.logger import get_logger
from lib.storage import LocalStorage
from lib.storage_gdrive import GoogleDriveStorage

logger = get_logger(__name__)
_console = logging.StreamHandler(sys.stdout)
_console.setLevel(logging.INFO)
_console.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(_console)


# Folder names to skip on both directions (archives, hidden, system).
_SKIP_FOLDER_NAMES = {"_archive_md"}


@dataclass
class Target:
    name: str
    local_subdir: str
    pull_from: str
    push_to: str


def _load_config(path: Path) -> List[Target]:
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not raw or "targets" not in raw:
        raise ValueError(f"{path}: missing 'targets' key")
    targets: List[Target] = []
    for t in raw["targets"]:
        if not all(k in t for k in ("name", "local_subdir", "pull_from")):
            raise ValueError(f"{path}: target {t!r} missing required keys "
                             f"(name, local_subdir, pull_from).")
        targets.append(Target(
            name=t["name"],
            local_subdir=t["local_subdir"].strip("/"),
            pull_from=t["pull_from"],
            push_to=t.get("push_to") or t["pull_from"],
        ))
    return targets


def _build_drive_storage(folder_id: str, credentials: str, token: str) -> GoogleDriveStorage:
    return GoogleDriveStorage(
        credentials_path=credentials,
        token_path=token,
        root_folder_id=folder_id,
    )


# ---------- Drive walker (skips _archive_md/) ----------

def _walk_drive(drive: GoogleDriveStorage, rel: str = "") -> List[Tuple[str, float]]:
    """Recursive list of files under `rel`, with mtimes. Skips _SKIP_FOLDER_NAMES."""
    out: List[Tuple[str, float]] = []
    # Use the underlying client directly so we can skip folders by name.
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
                else:
                    from lib.storage_gdrive import _parse_modtime
                    out.append((child_rel, _parse_modtime(item.get("modifiedTime"))))
                    # Warm caches so subsequent read_bytes / _get_mime are fast.
                    drive._path_to_id[child_rel] = item["id"]
                    drive._path_to_mime[child_rel] = item.get("mimeType", "")
            page_token = res.get("nextPageToken")
            if not page_token:
                break
    return out


# ---------- Local walker ----------

def _walk_local(local: LocalStorage, subdir: str) -> List[str]:
    """Recursive list of files under `subdir` (paths relative to subdir)."""
    base = Path(local.base) / subdir
    if not base.is_dir():
        return []
    out: List[str] = []
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        out.append(str(p.relative_to(base).as_posix()))
    return out


# ---------- Pull ----------

def _pull_target(t: Target, mirror: LocalStorage,
                 credentials: str, token: str,
                 dry_run: bool, prune: bool) -> Tuple[int, int, int]:
    """Returns (synced, failed, pruned)."""
    logger.info(f"=== PULL target={t.name} (drive {t.pull_from} -> "
                f"local {mirror.base}/{t.local_subdir}) ===")
    drive = _build_drive_storage(t.pull_from, credentials, token)
    drive_files = _walk_drive(drive)
    logger.info(f"  {len(drive_files)} files on Drive.")

    synced = 0
    failed = 0
    drive_paths: Set[str] = set()
    for rel, _mtime in drive_files:
        drive_paths.add(rel)
        local_rel = f"{t.local_subdir}/{rel}"
        if dry_run:
            logger.info(f"  [DRY] pull {rel}")
            continue
        try:
            content = drive.read_bytes(rel)
            mirror.write_bytes(local_rel, content)
            logger.info(f"  pull {rel} ({len(content)} bytes)")
            synced += 1
        except Exception as e:
            logger.error(f"  FAILED pull {rel}: {e}")
            failed += 1

    pruned = 0
    if prune:
        local_files = set(_walk_local(mirror, t.local_subdir))
        to_delete = local_files - drive_paths
        for rel in sorted(to_delete):
            local_rel = f"{t.local_subdir}/{rel}"
            if dry_run:
                logger.info(f"  [DRY] prune local {local_rel}")
                continue
            try:
                mirror.remove(local_rel)
                logger.info(f"  prune local {local_rel}")
                pruned += 1
            except Exception as e:
                logger.error(f"  FAILED prune {local_rel}: {e}")

    logger.info(f"  synced={synced} failed={failed} pruned={pruned}")
    return synced, failed, pruned


# ---------- Push ----------

def _push_target(t: Target, mirror: LocalStorage,
                 credentials: str, token: str,
                 dry_run: bool, prune: bool) -> Tuple[int, int, int]:
    logger.info(f"=== PUSH target={t.name} (local {mirror.base}/{t.local_subdir} "
                f"-> drive {t.push_to}) ===")
    drive = _build_drive_storage(t.push_to, credentials, token)
    local_files = _walk_local(mirror, t.local_subdir)
    logger.info(f"  {len(local_files)} files locally.")

    synced = 0
    failed = 0
    local_paths: Set[str] = set(local_files)
    for rel in local_files:
        if dry_run:
            logger.info(f"  [DRY] push {rel}")
            continue
        try:
            with open(Path(mirror.base) / t.local_subdir / rel, "rb") as f:
                content = f.read()
            # GoogleDriveStorage.write_bytes already handles gdoc import for
            # .md paths and plain bytes for everything else.
            drive.write_bytes(rel, content)
            logger.info(f"  push {rel} ({len(content)} bytes)")
            synced += 1
        except Exception as e:
            logger.error(f"  FAILED push {rel}: {e}")
            failed += 1

    pruned = 0
    if prune:
        drive_files = {p for p, _ in _walk_drive(drive)}
        to_delete = drive_files - local_paths
        for rel in sorted(to_delete):
            if dry_run:
                logger.info(f"  [DRY] prune drive {rel}")
                continue
            try:
                drive.remove(rel)
                logger.info(f"  prune drive {rel}")
                pruned += 1
            except Exception as e:
                logger.error(f"  FAILED prune {rel}: {e}")

    logger.info(f"  synced={synced} failed={failed} pruned={pruned}")
    return synced, failed, pruned


# ---------- Main ----------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("direction", choices=["pull", "push"],
                        help="Sync direction.")
    parser.add_argument("--config", default="config/sync.yaml",
                        help="Path to sync config (default: config/sync.yaml).")
    parser.add_argument("--target",
                        help="Only sync the named target (default: all).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Log actions without performing them.")
    parser.add_argument("--prune", action="store_true",
                        help="Delete destination-side files not present in source.")
    parser.add_argument("--mirror-dir",
                        default=os.environ.get("STORAGE_MIRROR_DIR"),
                        help="Local mirror dir (default: $STORAGE_MIRROR_DIR).")
    parser.add_argument("--credentials",
                        default=os.environ.get("GDRIVE_CREDENTIALS")
                        or os.path.expanduser("~/.openclaw/gdrive-ops-credentials.json"))
    parser.add_argument("--token",
                        default=os.environ.get("GDRIVE_TOKEN")
                        or os.path.expanduser("~/.openclaw/gdrive-ops-token.json"))
    args = parser.parse_args()

    if not args.mirror_dir:
        logger.error("STORAGE_MIRROR_DIR is not set and --mirror-dir not given.")
        return 2
    if not args.mirror_dir.startswith("/"):
        logger.error(f"mirror dir must be absolute, got: {args.mirror_dir}")
        return 2
    os.makedirs(args.mirror_dir, exist_ok=True)

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / config_path
    if not config_path.exists():
        logger.error(f"Config not found: {config_path}. Copy "
                     f"config/sync.yaml.example to config/sync.yaml and fill in IDs.")
        return 2

    targets = _load_config(config_path)
    if args.target:
        targets = [t for t in targets if t.name == args.target]
        if not targets:
            logger.error(f"No target named {args.target!r} in {config_path}.")
            return 2

    mirror = LocalStorage(args.mirror_dir)

    totals = [0, 0, 0]
    for t in targets:
        if args.direction == "pull":
            s, f, p = _pull_target(t, mirror, args.credentials, args.token,
                                   args.dry_run, args.prune)
        else:
            s, f, p = _push_target(t, mirror, args.credentials, args.token,
                                   args.dry_run, args.prune)
        totals[0] += s
        totals[1] += f
        totals[2] += p

    logger.info(f"=== TOTAL synced={totals[0]} failed={totals[1]} pruned={totals[2]} ===")
    return 0 if totals[1] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
