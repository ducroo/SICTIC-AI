from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator

from googleapiclient.errors import HttpError
from lib.storage_gdrive import GoogleDriveStorage, _FOLDER_MIME, _GDOC_MIME, _parse_modtime

from .types import SnapshotEntry
from .util import clean_rel, is_excluded, is_hidden_rel, sha256_bytes


UNSUPPORTED_MIMES = {
    "application/vnd.google-apps.spreadsheet": "Google Sheets",
    "application/vnd.google-apps.presentation": "Google Slides",
    "application/vnd.google-apps.drawing": "Google Drawings",
    "application/vnd.google-apps.form": "Google Forms",
}
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
logger = logging.getLogger(__name__)


def _execute_with_retries(request, *, context: str, retries: int = 5):
    delay = 2.0
    for attempt in range(1, retries + 1):
        try:
            return request.execute(num_retries=3)
        except HttpError as exc:
            status = getattr(exc.resp, "status", None)
            if status not in {429, 500, 502, 503, 504} or attempt == retries:
                raise
            logger.warning("%s failed with HTTP %s; retry %s/%s", context, status, attempt, retries)
        except (TimeoutError, OSError) as exc:
            if attempt == retries:
                raise
            logger.warning("%s timed out/failed: %s; retry %s/%s", context, exc, attempt, retries)
        time.sleep(delay)
        delay = min(delay * 2, 30.0)


class DriveTree:
    def __init__(
        self,
        *,
        root_folder_id: str,
        credentials_path: str,
        token_path: str,
        exclude: list[str] | None = None,
    ):
        self.storage = GoogleDriveStorage(
            credentials_path=credentials_path,
            token_path=token_path,
            root_folder_id=root_folder_id,
        )
        self.exclude = exclude or []

    def scan(self) -> tuple[dict[str, SnapshotEntry], list[str], list[str]]:
        logger.info("Drive scan started")
        self.storage._resolve_root_folder()
        service = self.storage._ensure_service()
        entries: dict[str, SnapshotEntry] = {}
        warnings: list[str] = []
        failures: list[str] = []
        stack: list[tuple[str, str]] = [(self.storage.root_folder_id, "")]
        visited = 0

        while stack:
            parent_id, prefix = stack.pop()
            page_token = None
            seen_names: set[str] = set()
            while True:
                res = _execute_with_retries(
                    service.files().list(
                        q=f"'{parent_id}' in parents and trashed=false",
                        fields="nextPageToken,files(id,name,mimeType,modifiedTime,size)",
                        pageSize=1000,
                        pageToken=page_token,
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True,
                    ),
                    context=f"Drive list {prefix or '/'}",
                )
                for item in res.get("files", []):
                    visited += 1
                    if visited == 1 or visited % 25 == 0:
                        logger.info("Drive scan visited %s entries; current=%s", visited, item.get("name", ""))
                    name = item["name"]
                    rel = f"{prefix}/{name}" if prefix else name
                    mime = item.get("mimeType", "")
                    if is_hidden_rel(rel) or is_excluded(rel, self.exclude):
                        continue
                    if name in seen_names:
                        failures.append(f"{rel}: duplicate Drive name in folder")
                        continue
                    seen_names.add(name)
                    if mime == SHORTCUT_MIME:
                        warnings.append(f"{rel}: ignored Drive shortcut")
                        continue
                    if mime in UNSUPPORTED_MIMES:
                        failures.append(f"{rel}: unsupported {UNSUPPORTED_MIMES[mime]}")
                        continue
                    if mime.startswith("application/vnd.google-apps.") and mime not in {_FOLDER_MIME, _GDOC_MIME}:
                        failures.append(f"{rel}: unsupported Google native type {mime}")
                        continue
                    if mime == _FOLDER_MIME:
                        entries[rel] = SnapshotEntry(
                            path=rel,
                            type="folder",
                            mtime=_parse_modtime(item.get("modifiedTime")),
                            drive_id=item["id"],
                            mime_type=mime,
                        )
                        self.storage._path_to_id[rel] = item["id"]
                        self.storage._path_to_mime[rel] = mime
                        stack.append((item["id"], rel))
                        continue
                    self.storage._path_to_id[rel] = item["id"]
                    self.storage._path_to_mime[rel] = mime
                    try:
                        content = self.storage.read_bytes(rel)
                    except Exception as exc:
                        failures.append(f"{rel}: failed to read Drive file: {exc}")
                        continue
                    entries[rel] = SnapshotEntry(
                        path=rel,
                        type="file",
                        sha256=sha256_bytes(content),
                        size=len(content),
                        mtime=_parse_modtime(item.get("modifiedTime")),
                        drive_id=item["id"],
                        mime_type=mime,
                    )
                page_token = res.get("nextPageToken")
                if not page_token:
                    break
        logger.info(
            "Drive scan finished: entries=%s warnings=%s failures=%s",
            len(entries),
            len(warnings),
            len(failures),
        )
        return entries, warnings, failures

    def iter_entries_with_content(
        self,
        *,
        checkpoint: dict[str, SnapshotEntry] | None = None,
        local_snapshot: dict[str, SnapshotEntry] | None = None,
    ) -> Iterator[tuple[SnapshotEntry | None, bytes | None, str | None, str | None]]:
        """Yield Drive entries depth-first, downloading file content as entries appear.

        The tuple is (entry, content, warning, failure). Folder entries have
        content=None. Unsupported/skipped entries are reported as warning/failure
        tuples and traversal continues where possible.
        """
        logger.info("Drive streaming walk started")
        self.storage._resolve_root_folder()
        service = self.storage._ensure_service()
        stack: list[tuple[str, str]] = [(self.storage.root_folder_id, "")]
        visited = 0
        checkpoint = checkpoint or {}
        local_snapshot = local_snapshot or {}

        while stack:
            parent_id, prefix = stack.pop()
            page_token = None
            seen_names: set[str] = set()
            while True:
                res = _execute_with_retries(
                    service.files().list(
                        q=f"'{parent_id}' in parents and trashed=false",
                        fields="nextPageToken,files(id,name,mimeType,modifiedTime,size)",
                        pageSize=1000,
                        pageToken=page_token,
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True,
                    ),
                    context=f"Drive streaming list {prefix or '/'}",
                )
                for item in res.get("files", []):
                    visited += 1
                    name = item["name"]
                    rel = f"{prefix}/{name}" if prefix else name
                    mime = item.get("mimeType", "")
                    if visited == 1 or visited % 25 == 0:
                        logger.info("Drive streaming walk visited %s entries; current=%s", visited, rel)
                    if is_hidden_rel(rel) or is_excluded(rel, self.exclude):
                        continue
                    if name in seen_names:
                        yield None, None, None, f"{rel}: duplicate Drive name in folder"
                        continue
                    seen_names.add(name)
                    if mime == SHORTCUT_MIME:
                        yield None, None, f"{rel}: ignored Drive shortcut", None
                        continue
                    if mime in UNSUPPORTED_MIMES:
                        yield None, None, None, f"{rel}: unsupported {UNSUPPORTED_MIMES[mime]}"
                        continue
                    if mime.startswith("application/vnd.google-apps.") and mime not in {_FOLDER_MIME, _GDOC_MIME}:
                        yield None, None, None, f"{rel}: unsupported Google native type {mime}"
                        continue
                    if mime == _FOLDER_MIME:
                        entry = SnapshotEntry(
                            path=rel,
                            type="folder",
                            mtime=_parse_modtime(item.get("modifiedTime")),
                            drive_id=item["id"],
                            mime_type=mime,
                        )
                        self.storage._path_to_id[rel] = item["id"]
                        self.storage._path_to_mime[rel] = mime
                        stack.append((item["id"], rel))
                        yield entry, None, None, None
                        continue
                    self.storage._path_to_id[rel] = item["id"]
                    self.storage._path_to_mime[rel] = mime
                    completed = checkpoint.get(rel)
                    local_entry = local_snapshot.get(rel)
                    item_mtime = _parse_modtime(item.get("modifiedTime"))
                    if (
                        completed is not None
                        and local_entry is not None
                        and completed.type == "file"
                        and local_entry.type == "file"
                        and completed.sha256 is not None
                        and local_entry.sha256 == completed.sha256
                        and completed.drive_id == item["id"]
                        and completed.mime_type == mime
                        and completed.mtime == item_mtime
                    ):
                        yield completed, None, None, None
                        continue
                    try:
                        content = self.storage.read_bytes(rel)
                    except Exception as exc:
                        yield None, None, None, f"{rel}: failed to read Drive file: {exc}"
                        continue
                    yield (
                        SnapshotEntry(
                            path=rel,
                            type="file",
                            sha256=sha256_bytes(content),
                            size=len(content),
                            mtime=item_mtime,
                            drive_id=item["id"],
                            mime_type=mime,
                        ),
                        content,
                        None,
                        None,
                    )
                page_token = res.get("nextPageToken")
                if not page_token:
                    break
        logger.info("Drive streaming walk finished: visited=%s", visited)

    def read_bytes(self, rel: str) -> bytes:
        return self.storage.read_bytes(clean_rel(rel))

    def write_bytes(self, rel: str, content: bytes) -> None:
        self.storage.write_bytes(clean_rel(rel), content)

    def mkdir(self, rel: str) -> None:
        self.storage.mkdir(clean_rel(rel))

    def remove(self, rel: str) -> None:
        rel = clean_rel(rel)
        if rel:
            self.storage.remove(rel)

    def start_page_token(self) -> str | None:
        service = self.storage._ensure_service()
        try:
            return _execute_with_retries(
                service.changes().getStartPageToken(supportsAllDrives=True),
                context="Drive start page token",
            ).get("startPageToken")
        except Exception:
            return None
