"""
One-shot migration: convert every .md file under a Drive folder into a Google Doc
(in place, same name), moving the original into _archive_md/<original_path>/.

After running, lib/storage_gdrive.py reads/writes .md paths as Google Docs (export
via text/markdown, import via text/markdown). This script is what flips the
storage from raw markdown blobs to native gdocs.

Usage:
    # dry-run against the configured STORAGE_PATH root
    python scripts/convert_md_to_gdoc.py

    # dry-run against a specific test folder
    python scripts/convert_md_to_gdoc.py --root-folder AI-root --summary-only
    python scripts/convert_md_to_gdoc.py --root-folder-id 1A2B3C...

    # apply for real
    python scripts/convert_md_to_gdoc.py --root-folder AI-root --apply

Idempotent: files already of type application/vnd.google-apps.document are
skipped, and anything inside the archive folder is skipped.
"""
from __future__ import annotations

import argparse
import io
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

# Make `lib` importable when invoked as `python scripts/convert_md_to_gdoc.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lib.env  # noqa: F401  triggers .env load
from google.auth.transport.requests import Request as AuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

import logging

from lib.logger import get_logger

logger = get_logger(__name__)
# Also echo to stdout so the user sees progress without tailing logs/sictic-ai.log.
_console = logging.StreamHandler(sys.stdout)
_console.setLevel(logging.INFO)
_console.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(_console)

_SCOPES = ["https://www.googleapis.com/auth/drive"]
_FOLDER_MIME = "application/vnd.google-apps.folder"
_GDOC_MIME = "application/vnd.google-apps.document"
_MD_MIME = "text/markdown"
_FIELDS = "id,name,mimeType,parents,trashed"


@dataclass
class FileNode:
    id: str
    name: str
    mime_type: str
    parent_id: str
    rel_path: str  # relative to root, posix-style


def _build_service(credentials_path: str, token_path: str):
    creds: Optional[Credentials] = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, _SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(AuthRequest())
    elif not (creds and creds.valid):
        flow = InstalledAppFlow.from_client_secrets_file(credentials_path, _SCOPES)
        creds = flow.run_local_server(port=0)
        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
        os.chmod(token_path, 0o600)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _escape_q(value: str) -> str:
    """Escape a string for use inside a Drive query single-quoted value."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _resolve_root_folder(service, root_spec: str) -> str:
    """Resolve a root spec as a Drive ID, "root", or a folder path/name.

    This mirrors lib.storage_gdrive.GoogleDriveStorage so migration commands can
    use the same human-friendly STORAGE_PATH values as the runtime.
    """
    spec = (root_spec or "root").strip().strip("/")
    if not spec or spec == "root":
        return "root"

    # First try the value as a real Drive folder ID. This preserves existing
    # behavior and avoids ambiguity when an ID happens to look path-like.
    if "/" not in spec:
        try:
            meta = service.files().get(
                fileId=spec,
                fields="id,mimeType",
                supportsAllDrives=True,
            ).execute()
            if meta.get("mimeType") == _FOLDER_MIME:
                return meta["id"]
        except HttpError:
            pass

    current_id = "root"
    parts = [p for p in spec.split("/") if p and p != "root"]
    for index, part in enumerate(parts):
        res = service.files().list(
            q=(
                f"'{current_id}' in parents and "
                f"name='{_escape_q(part)}' and "
                f"mimeType='{_FOLDER_MIME}' and trashed=false"
            ),
            fields=f"files({_FIELDS})",
            pageSize=10,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        files = res.get("files", [])

        # Match runtime behavior for a single friendly name such as AI-root:
        # if it is not under My Drive root, also search globally.
        if not files and index == 0 and len(parts) == 1:
            res = service.files().list(
                q=(
                    f"name='{_escape_q(part)}' and "
                    f"mimeType='{_FOLDER_MIME}' and trashed=false"
                ),
                fields=f"files({_FIELDS})",
                pageSize=10,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()
            files = res.get("files", [])

        if not files:
            raise FileNotFoundError(f"Google Drive root folder not found: {root_spec!r}")

        files.sort(key=lambda f: f["id"])
        current_id = files[0]["id"]

    return current_id


def _walk(
    service,
    root_id: str,
    archive_name: str,
    *,
    progress_every: int = 250,
) -> List[FileNode]:
    """BFS the Drive tree, skipping the archive subtree."""
    out: List[FileNode] = []
    queue: List[tuple] = [(root_id, "")]
    archive_id: Optional[str] = None
    folders_seen = 0

    # First, find (or note absence of) the archive folder at root so we can skip it.
    page_token = None
    while True:
        res = service.files().list(
            q=f"'{root_id}' in parents and name='{archive_name}' and "
              f"mimeType='{_FOLDER_MIME}' and trashed=false",
            fields=f"nextPageToken,files({_FIELDS})",
            pageSize=10,
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        for f in res.get("files", []):
            archive_id = f["id"]
        page_token = res.get("nextPageToken")
        if not page_token:
            break

    while queue:
        parent_id, prefix = queue.pop()
        folders_seen += 1
        if progress_every > 0 and folders_seen % progress_every == 0:
            logger.info(f"Walk progress: {folders_seen} folders scanned, {len(out)} files found...")
        page_token = None
        while True:
            res = service.files().list(
                q=f"'{parent_id}' in parents and trashed=false",
                fields=f"nextPageToken,files({_FIELDS})",
                pageSize=1000,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()
            for item in res.get("files", []):
                if archive_id and item["id"] == archive_id:
                    continue
                rel = f"{prefix}{item['name']}" if not prefix else f"{prefix}/{item['name']}"
                node = FileNode(
                    id=item["id"],
                    name=item["name"],
                    mime_type=item.get("mimeType", ""),
                    parent_id=parent_id,
                    rel_path=rel,
                )
                if item.get("mimeType") == _FOLDER_MIME:
                    queue.append((item["id"], rel))
                else:
                    out.append(node)
            page_token = res.get("nextPageToken")
            if not page_token:
                break
    return out


def _ensure_folder(service, parent_id: str, name: str, cache: Dict[str, str]) -> str:
    """Return folder ID for `name` under `parent_id`, creating it if missing."""
    cache_key = f"{parent_id}/{name}"
    if cache_key in cache:
        return cache[cache_key]
    res = service.files().list(
        q=f"'{parent_id}' in parents and name='{name.replace(chr(39), chr(92)+chr(39))}' "
          f"and mimeType='{_FOLDER_MIME}' and trashed=false",
        fields=f"files({_FIELDS})",
        pageSize=10,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    files = res.get("files", [])
    if files:
        cache[cache_key] = files[0]["id"]
        return files[0]["id"]
    created = service.files().create(
        body={"name": name, "mimeType": _FOLDER_MIME, "parents": [parent_id]},
        fields="id",
        supportsAllDrives=True,
    ).execute()
    cache[cache_key] = created["id"]
    return created["id"]


def _ensure_archive_path(service, root_id: str, archive_name: str,
                         rel_parent_path: str, cache: Dict[str, str]) -> str:
    """Mirror the relative parent path under <root>/<archive_name>/."""
    parent_id = _ensure_folder(service, root_id, archive_name, cache)
    if not rel_parent_path:
        return parent_id
    for segment in rel_parent_path.split("/"):
        if not segment:
            continue
        parent_id = _ensure_folder(service, parent_id, segment, cache)
    return parent_id


def _download_bytes(service, file_id: str) -> bytes:
    buf = io.BytesIO()
    req = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    downloader = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--root-folder", default=None,
                        help="Drive folder ID, root, or folder path/name to walk.")
    parser.add_argument("--root-folder-id", default=None,
                        help="Deprecated alias for --root-folder.")
    parser.add_argument("--archive-name", default="_archive_md",
                        help="Folder name (under root) to move originals into.")
    parser.add_argument("--apply", action="store_true",
                        help="Actually perform conversions. Without this, dry-run only.")
    parser.add_argument("--summary-only", action="store_true",
                        help="Only print counts, not one line per file in dry-run mode.")
    parser.add_argument("--progress-every", type=int, default=250,
                        help="During Drive walk, print progress every N folders. Use 0 to disable.")
    parser.add_argument("--credentials",
                        default=os.environ.get("GDRIVE_CREDENTIALS")
                        or os.path.expanduser("~/.openclaw/gdrive-ops-credentials.json"))
    parser.add_argument("--token",
                        default=os.environ.get("GDRIVE_TOKEN")
                        or os.path.expanduser("~/.openclaw/gdrive-ops-token.json"))
    args = parser.parse_args()

    root_spec = args.root_folder or args.root_folder_id or os.environ.get("STORAGE_PATH") or "root"
    dry = not args.apply

    logger.info(f"Root folder: {root_spec}")
    logger.info(f"Archive subfolder: {args.archive_name}")
    logger.info(f"Mode: {'DRY-RUN' if dry else 'APPLY'}")

    service = _build_service(args.credentials, args.token)
    root_id = _resolve_root_folder(service, root_spec)
    logger.info(f"Resolved root folder ID: {root_id}")
    all_files = _walk(
        service,
        root_id,
        args.archive_name,
        progress_every=args.progress_every,
    )

    md_candidates = [f for f in all_files if f.name.lower().endswith(".md")]
    to_convert = [f for f in md_candidates if f.mime_type != _GDOC_MIME]
    already_gdoc = [f for f in md_candidates if f.mime_type == _GDOC_MIME]

    logger.info(f"Found {len(md_candidates)} .md files total "
                f"({len(already_gdoc)} already gdocs, {len(to_convert)} to convert).")

    if not to_convert:
        logger.info("Nothing to do.")
        return 0

    folder_cache: Dict[str, str] = {}
    converted = 0
    failed = 0

    for node in to_convert:
        rel_parent = "/".join(node.rel_path.split("/")[:-1])
        action = (
            f"convert '{node.rel_path}' (id={node.id}, mime={node.mime_type}) -> gdoc, "
            f"archive original at '{args.archive_name}/{node.rel_path}'"
        )
        if dry and args.summary_only:
            continue
        if dry:
            logger.info(f"[DRY] {action}")
            continue

        logger.info(action)
        try:
            content = _download_bytes(service, node.id)

            # Create new gdoc with same name + parent, importing the markdown bytes.
            media = MediaIoBaseUpload(
                io.BytesIO(content), mimetype=_MD_MIME, resumable=False
            )
            service.files().create(
                body={
                    "name": node.name,
                    "parents": [node.parent_id],
                    "mimeType": _GDOC_MIME,
                },
                media_body=media,
                fields="id",
                supportsAllDrives=True,
            ).execute()

            # Move original into the archive subtree.
            archive_parent_id = _ensure_archive_path(
                service, root_id, args.archive_name, rel_parent, folder_cache
            )
            service.files().update(
                fileId=node.id,
                addParents=archive_parent_id,
                removeParents=node.parent_id,
                fields="id,parents",
                supportsAllDrives=True,
            ).execute()
            converted += 1
        except HttpError as e:
            failed += 1
            logger.error(f"FAILED on {node.rel_path}: {e}")

    if dry:
        logger.info(f"Dry-run summary: {len(to_convert)} files would be converted.")
    else:
        logger.info(f"Done. Converted: {converted}, failed: {failed}.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
