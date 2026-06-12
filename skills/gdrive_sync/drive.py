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


def _local_rel_for_drive_item(prefix: str, name: str, mime: str) -> str:
    local_name = name
    if mime == _GDOC_MIME and not name.lower().endswith(".md"):
        local_name = f"{name}.md"
    return clean_rel(f"{prefix}/{local_name}" if prefix else local_name)


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

    def _get_file_metadata(self, file_id: str) -> dict | None:
        service = self.storage._ensure_service()
        try:
            return _execute_with_retries(
                service.files().get(
                    fileId=file_id,
                    fields="id,name,mimeType,modifiedTime,size,parents,trashed",
                    supportsAllDrives=True,
                ),
                context=f"Drive get metadata {file_id}",
            )
        except HttpError as exc:
            if getattr(exc.resp, "status", None) == 404:
                return None
            raise

    def _path_for_file(self, file_meta: dict) -> str | None:
        self.storage._resolve_root_folder()
        parts = [file_meta["name"]]
        parents = file_meta.get("parents") or []
        seen = {file_meta["id"]}
        while parents:
            parent_id = parents[0]
            if parent_id == self.storage.root_folder_id:
                return "/".join(reversed(parts))
            if parent_id in seen:
                return None
            seen.add(parent_id)
            parent_meta = self._get_file_metadata(parent_id)
            if not parent_meta or parent_meta.get("trashed"):
                return None
            parts.append(parent_meta["name"])
            parents = parent_meta.get("parents") or []
        return None

    def list_changes(self, page_token: str) -> tuple[list[dict], str]:
        service = self.storage._ensure_service()
        changes: list[dict] = []
        token = page_token
        new_start_page_token: str | None = None
        while True:
            res = _execute_with_retries(
                service.changes().list(
                    pageToken=token,
                    pageSize=1000,
                    includeRemoved=True,
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                    fields=(
                        "nextPageToken,newStartPageToken,"
                        "changes(fileId,removed,file(id,name,mimeType,modifiedTime,size,parents,trashed))"
                    ),
                ),
                context="Drive changes.list",
            )
            changes.extend(res.get("changes", []))
            next_page_token = res.get("nextPageToken")
            if next_page_token:
                token = next_page_token
                continue
            new_start_page_token = res.get("newStartPageToken") or token
            break
        logger.info("Drive changes.list returned %s changes", len(changes))
        return changes, new_start_page_token

    def entry_for_change(self, change: dict) -> tuple[SnapshotEntry | None, bytes | None, str | None, str | None]:
        file_meta = change.get("file")
        file_id = change.get("fileId")
        if change.get("removed") or not file_meta or file_meta.get("trashed"):
            return None, None, None, None
        drive_rel = self._path_for_file(file_meta)
        if not drive_rel:
            return None, None, None, None
        mime = file_meta.get("mimeType", "")
        prefix, _, name = drive_rel.rpartition("/")
        rel = _local_rel_for_drive_item(prefix, name, mime)
        if is_hidden_rel(rel) or is_excluded(rel, self.exclude):
            return None, None, None, None
        if mime == SHORTCUT_MIME:
            return None, None, f"{rel}: ignored Drive shortcut", None
        if mime in UNSUPPORTED_MIMES:
            return None, None, None, f"{rel}: unsupported {UNSUPPORTED_MIMES[mime]}"
        if mime.startswith("application/vnd.google-apps.") and mime not in {_FOLDER_MIME, _GDOC_MIME}:
            return None, None, None, f"{rel}: unsupported Google native type {mime}"
        self.storage._path_to_id[rel] = file_id
        self.storage._path_to_mime[rel] = mime
        if mime == _FOLDER_MIME:
            return (
                SnapshotEntry(
                    path=rel,
                    type="folder",
                    mtime=_parse_modtime(file_meta.get("modifiedTime")),
                    drive_id=file_id,
                    mime_type=mime,
                ),
                None,
                None,
                None,
            )
        try:
            content = self.storage.read_bytes(rel)
        except Exception as exc:
            return None, None, None, f"{rel}: failed to read Drive file: {exc}"
        return (
            SnapshotEntry(
                path=rel,
                type="file",
                sha256=sha256_bytes(content),
                size=len(content),
                mtime=_parse_modtime(file_meta.get("modifiedTime")),
                drive_id=file_id,
                mime_type=mime,
            ),
            content,
            None,
            None,
        )

    def iter_subtree_with_content(
        self,
        *,
        root_id: str,
        root_path: str,
        checkpoint: dict[str, SnapshotEntry] | None = None,
        local_snapshot: dict[str, SnapshotEntry] | None = None,
    ) -> Iterator[tuple[SnapshotEntry | None, bytes | None, str | None, str | None]]:
        yield from self._iter_entries_with_content_from(
            [(root_id, root_path)],
            checkpoint=checkpoint,
            local_snapshot=local_snapshot,
            log_label=f"Drive subtree walk {root_path}",
        )

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
                    mime = item.get("mimeType", "")
                    rel = _local_rel_for_drive_item(prefix, name, mime)
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
        self.storage._resolve_root_folder()
        yield from self._iter_entries_with_content_from(
            [(self.storage.root_folder_id, "")],
            checkpoint=checkpoint,
            local_snapshot=local_snapshot,
            log_label="Drive streaming walk",
        )

    def _iter_entries_with_content_from(
        self,
        stack: list[tuple[str, str]],
        *,
        checkpoint: dict[str, SnapshotEntry] | None = None,
        local_snapshot: dict[str, SnapshotEntry] | None = None,
        log_label: str,
    ) -> Iterator[tuple[SnapshotEntry | None, bytes | None, str | None, str | None]]:
        logger.info("%s started", log_label)
        service = self.storage._ensure_service()
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
                    mime = item.get("mimeType", "")
                    rel = _local_rel_for_drive_item(prefix, name, mime)
                    if visited == 1 or visited % 25 == 0:
                        logger.info("%s visited %s entries; current=%s", log_label, visited, rel)
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
        logger.info("%s finished: visited=%s", log_label, visited)

    def read_bytes(self, rel: str) -> bytes:
        return self.storage.read_bytes(clean_rel(rel))

    def write_bytes(self, rel: str, content: bytes) -> None:
        self.storage.write_bytes(clean_rel(rel), content)

    def entry_after_write(self, rel: str, content: bytes) -> SnapshotEntry:
        rel = clean_rel(rel)
        file_id = self.storage._resolve(rel)
        mime = self.storage._path_to_mime.get(rel)
        if file_id and not mime:
            mime = self.storage._get_mime(rel, file_id)
        return SnapshotEntry(
            path=rel,
            type="file",
            sha256=sha256_bytes(content),
            size=len(content),
            mtime=self.storage.mtime(rel),
            drive_id=file_id,
            mime_type=mime,
        )

    def mkdir(self, rel: str) -> None:
        self.storage.mkdir(clean_rel(rel))

    def entry_after_mkdir(self, rel: str) -> SnapshotEntry:
        rel = clean_rel(rel)
        file_id = self.storage._resolve(rel)
        return SnapshotEntry(
            path=rel,
            type="folder",
            mtime=self.storage.mtime(rel) if file_id else None,
            drive_id=file_id,
            mime_type=_FOLDER_MIME,
        )

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
