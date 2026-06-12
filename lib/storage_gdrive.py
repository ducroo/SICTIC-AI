"""
GoogleDriveStorage — Storage backend that talks directly to the Google Drive API
via google-api-python-client. No rclone in the loop.

OAuth: uses an installed-app (Desktop) OAuth client. credentials.json is read
from `credentials_path`; the refresh token is cached at `token_path`. First run
opens a browser via run_local_server(port=0); subsequent runs reuse the token.

Drive's API is file-ID-centric, not path-centric. We maintain caches that map
relative paths -> Drive IDs and dir paths -> child listings, so a path like
"datasets/sictic_members/foo.pdf" doesn't trigger 3 API calls on every access.
"""
from __future__ import annotations

import io
import os
import threading
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple

from google.auth.transport.requests import Request as AuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload


_SCOPES = ["https://www.googleapis.com/auth/drive"]
_FOLDER_MIME = "application/vnd.google-apps.folder"
_GDOC_MIME = "application/vnd.google-apps.document"
_MD_MIME = "text/markdown"
_FIELDS = "id,name,mimeType,modifiedTime,size"


def _is_md_path(rel: str) -> bool:
    return rel.lower().endswith(".md")


def _sanitize_markdown_upload(content: bytes) -> bytes:
    return bytes(
        byte
        for byte in content
        if byte in {0x09, 0x0A, 0x0D} or byte >= 0x20
    ).replace(b"\x7f", b"")


def _parse_modtime(s: Optional[str]) -> float:
    if not s:
        return 0.0
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _escape_q(name: str) -> str:
    """Escape a string for use inside a Drive query single-quoted value."""
    return name.replace("\\", "\\\\").replace("'", "\\'")


class GoogleDriveStorage:
    def __init__(
        self,
        credentials_path: str,
        token_path: str,
        root_folder_id: str = "root",
        local_cache_dir: Optional[str] = None,
    ):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self._root_folder_spec = root_folder_id or "root"
        self.root_folder_id = self._root_folder_spec
        self._root_resolved = self._root_folder_spec == "root"
        self._local_cache_dir = Path(
            local_cache_dir
            or os.path.expanduser("~/.cache/sictic/gdrive-materialized")
        )
        self._local_cache_dir.mkdir(parents=True, exist_ok=True)

        self._service = None
        self._service_lock = threading.Lock()

        # rel-path -> Drive file ID (None means known-nonexistent)
        self._path_to_id: Dict[str, Optional[str]] = {"": root_folder_id}
        # rel-path -> Drive mimeType (populated alongside _path_to_id)
        self._path_to_mime: Dict[str, str] = {"": _FOLDER_MIME}
        # dir rel-path -> list of child metadata dicts
        self._dir_children: Dict[str, List[dict]] = {}

    # ---------- OAuth / service ----------

    def _ensure_service(self):
        if self._service is not None:
            return self._service
        with self._service_lock:
            if self._service is not None:
                return self._service
            creds = self._load_or_authorize()
            self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
            return self._service

    def _load_or_authorize(self) -> Credentials:
        creds: Optional[Credentials] = None
        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, _SCOPES)
        if creds and creds.valid:
            return creds
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(AuthRequest())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, _SCOPES)
            creds = flow.run_local_server(port=0)
        Path(self.token_path).parent.mkdir(parents=True, exist_ok=True)
        with open(self.token_path, "w") as f:
            f.write(creds.to_json())
        os.chmod(self.token_path, 0o600)
        return creds

    def _resolve_root_folder(self) -> None:
        """Resolve root spec as either a Drive ID, 'root', or a folder path/name."""
        if self._root_resolved:
            return

        spec = self._root_folder_spec.strip().strip("/")
        if not spec or spec == "root":
            self.root_folder_id = "root"
            self._root_resolved = True
            self._path_to_id[""] = self.root_folder_id
            return

        service = self._ensure_service()

        # First try the value as a real Drive file ID. This preserves existing
        # deployments and avoids ambiguity when an ID happens to look path-like.
        if "/" not in spec:
            try:
                with self._service_lock:
                    meta = service.files().get(
                        fileId=spec,
                        fields="id,mimeType",
                        supportsAllDrives=True,
                    ).execute()
                if meta.get("mimeType") == _FOLDER_MIME:
                    self.root_folder_id = meta["id"]
                    self._root_resolved = True
                    self._path_to_id[""] = self.root_folder_id
                    self._path_to_mime[""] = _FOLDER_MIME
                    return
            except HttpError:
                pass

        current_id = "root"
        parts = [p for p in spec.split("/") if p]
        for index, part in enumerate(parts):
            q = (
                f"'{current_id}' in parents and "
                f"name='{_escape_q(part)}' and "
                f"mimeType='{_FOLDER_MIME}' and trashed=false"
            )
            with self._service_lock:
                res = service.files().list(
                    q=q,
                    fields=f"files({_FIELDS})",
                    pageSize=10,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                ).execute()
            files = res.get("files", [])

            # If a single-segment name was not found under My Drive root, also
            # allow a global folder-name search. This covers folders surfaced
            # from shared drives or shared-with-me contexts. If duplicates exist
            # the deterministic first ID is used; use an explicit ID to avoid
            # ambiguity.
            if not files and index == 0 and len(parts) == 1:
                with self._service_lock:
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
                raise FileNotFoundError(f"Google Drive root folder not found: {spec!r}")
            files.sort(key=lambda f: f["id"])
            current_id = files[0]["id"]

        self.root_folder_id = current_id
        self._root_resolved = True
        self._path_to_id = {"": self.root_folder_id}
        self._path_to_mime = {"": _FOLDER_MIME}
        self._dir_children = {}

    # ---------- path resolution ----------

    def _resolve(self, rel: str) -> Optional[str]:
        """Return the Drive file ID for rel, or None if it doesn't exist."""
        self._resolve_root_folder()
        # Use the common path validator to ensure strict relative paths
        from lib.storage import _validate_rel
        rel = _validate_rel(rel)
        rel = rel.strip("/")
        if rel in self._path_to_id:
            return self._path_to_id[rel]

        parent_rel = str(PurePosixPath(rel).parent)
        if parent_rel == ".":
            parent_rel = ""
        parent_id = self._resolve(parent_rel)
        if parent_id is None:
            self._path_to_id[rel] = None
            return None

        name = PurePosixPath(rel).name
        service = self._ensure_service()
        q = f"'{parent_id}' in parents and name='{_escape_q(name)}' and trashed=false"
        with self._service_lock:
            res = service.files().list(
                q=q,
                fields=f"files({_FIELDS})",
                pageSize=10,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()
        files = res.get("files", [])
        if not files:
            self._path_to_id[rel] = None
            return None
        if _is_md_path(rel):
            files = self._sort_md_candidates(files)
        else:
            # Drive permits same-name siblings; take the first deterministically.
            files.sort(key=lambda f: f["id"])
        selected = files[0]
        self._path_to_id[rel] = selected["id"]
        self._path_to_mime[rel] = selected.get("mimeType", "")
        return selected["id"]

    def _sort_md_candidates(self, files: List[dict]) -> List[dict]:
        """Return same-name .md candidates with Google Docs first.

        Drive names and MIME types are independent, so a logical .md path may
        be backed by either a native Google Doc named "x.md" or a legacy binary
        Markdown file named "x.md". The Google Doc is canonical when both exist.
        """
        return sorted(files, key=lambda f: (f.get("mimeType") != _GDOC_MIME, f["id"]))

    def _preferred_gdoc_for_write(self, rel: str, matches: List[dict]) -> Optional[dict]:
        gdocs = [item for item in matches if item.get("mimeType") == _GDOC_MIME]
        if len(gdocs) > 1:
            ids = ", ".join(item["id"] for item in gdocs)
            raise RuntimeError(
                f"{rel}: ambiguous Google Drive path. Found {len(gdocs)} non-trashed "
                f"Google Docs with this name: {ids}."
            )
        return gdocs[0] if gdocs else None

    def _delete_file_id(self, file_id: str) -> None:
        service = self._ensure_service()
        try:
            with self._service_lock:
                service.files().delete(fileId=file_id, supportsAllDrives=True).execute()
        except HttpError as e:
            if e.resp.status != 404:
                raise

    def _delete_legacy_md_siblings(self, rel: str, matches: List[dict], keep_id: Optional[str]) -> None:
        for item in matches:
            if item["id"] == keep_id or item.get("mimeType") == _GDOC_MIME:
                continue
            self._delete_file_id(item["id"])
        self._invalidate(rel)

    def _resolve_md_child_for_write(self, parent_id: str, rel: str, name: str) -> Tuple[Optional[dict], List[dict]]:
        matches = self._children_named(parent_id, name)
        existing_gdoc = self._preferred_gdoc_for_write(rel, matches)
        if existing_gdoc:
            self._path_to_id[rel] = existing_gdoc["id"]
            self._path_to_mime[rel] = existing_gdoc.get("mimeType", "")
        else:
            self._path_to_id[rel] = None
            self._path_to_mime.pop(rel, None)
        return existing_gdoc, matches

    def _read_legacy_md_bytes(self, fid: str) -> bytes:
        service = self._ensure_service()
        with self._service_lock:
            request = service.files().get_media(fileId=fid, supportsAllDrives=True)
            buf = io.BytesIO()
            downloader = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _, done = downloader.next_chunk(num_retries=5)
        return buf.getvalue()

    def _resolve_or_raise(self, rel: str) -> str:
        fid = self._resolve(rel)
        if fid is None:
            raise FileNotFoundError(rel)
        return fid

    def _children_named(self, parent_id: str, name: str) -> List[dict]:
        service = self._ensure_service()
        with self._service_lock:
            res = service.files().list(
                q=f"'{parent_id}' in parents and name='{_escape_q(name)}' and trashed=false",
                fields=f"files({_FIELDS})",
                pageSize=100,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()
        return sorted(res.get("files", []), key=lambda f: f["id"])

    def _resolve_unique_child_for_write(self, parent_id: str, rel: str, name: str) -> Optional[dict]:
        matches = self._children_named(parent_id, name)
        if len(matches) > 1:
            ids = ", ".join(item["id"] for item in matches)
            raise RuntimeError(
                f"{rel}: ambiguous Google Drive path. Found {len(matches)} non-trashed "
                f"files named {name!r} in the target folder: {ids}."
            )
        if not matches:
            self._path_to_id[rel] = None
            self._path_to_mime.pop(rel, None)
            return None
        self._path_to_id[rel] = matches[0]["id"]
        self._path_to_mime[rel] = matches[0].get("mimeType", "")
        return matches[0]

    def _list_children(self, rel: str) -> List[dict]:
        self._resolve_root_folder()
        rel = rel.strip("/")
        if rel in self._dir_children:
            return self._dir_children[rel]
        parent_id = self._resolve(rel)
        if parent_id is None:
            self._dir_children[rel] = []
            return []
        service = self._ensure_service()
        items: List[dict] = []
        page_token = None
        while True:
            with self._service_lock:
                res = service.files().list(
                    q=f"'{parent_id}' in parents and trashed=false",
                    fields=f"nextPageToken,files({_FIELDS})",
                    pageSize=1000,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                ).execute()
            items.extend(res.get("files", []))
            page_token = res.get("nextPageToken")
            if not page_token:
                break
        self._dir_children[rel] = items
        # Populate path cache for children too.
        prefix = f"{rel}/" if rel else ""
        for item in items:
            child_rel = f"{prefix}{item['name']}"
            if _is_md_path(child_rel):
                current_mime = self._path_to_mime.get(child_rel)
                item_mime = item.get("mimeType", "")
                if current_mime == _GDOC_MIME and item_mime != _GDOC_MIME:
                    continue
                if current_mime and current_mime != _GDOC_MIME and item_mime != _GDOC_MIME:
                    continue
            self._path_to_id[child_rel] = item["id"]
            self._path_to_mime[child_rel] = item.get("mimeType", "")
        return items

    def _invalidate(self, rel: str) -> None:
        rel = rel.strip("/")
        self._path_to_id.pop(rel, None)
        self._path_to_mime.pop(rel, None)
        parent = str(PurePosixPath(rel).parent) if rel else ""
        if parent == ".":
            parent = ""
        self._dir_children.pop(parent, None)
        # Drop any descendant cache entries.
        prefix = f"{rel}/" if rel else ""
        for k in [k for k in self._path_to_id if k.startswith(prefix)]:
            self._path_to_id.pop(k, None)
        for k in [k for k in self._path_to_mime if k.startswith(prefix)]:
            self._path_to_mime.pop(k, None)
        for k in [k for k in self._dir_children if k == rel or k.startswith(prefix)]:
            self._dir_children.pop(k, None)

    # ---------- Storage API ----------

    def _get_mime(self, rel: str, fid: str) -> str:
        """Return the cached Drive mimeType for rel, fetching with files().get if absent."""
        rel = rel.strip("/")
        mime = self._path_to_mime.get(rel)
        if mime:
            return mime
        service = self._ensure_service()
        with self._service_lock:
            meta = service.files().get(
                fileId=fid, fields="mimeType", supportsAllDrives=True
            ).execute()
        mime = meta.get("mimeType", "")
        self._path_to_mime[rel] = mime
        return mime

    def read_bytes(self, rel: str) -> bytes:
        fid = self._resolve_or_raise(rel)
        service = self._ensure_service()

        # num_retries triggers googleapiclient's built-in exponential backoff on
        # transient 5xx errors. Necessary on the gdoc-export path because Drive
        # sometimes returns 500 briefly after a re-import of new markdown content.
        if _is_md_path(rel):
            mime = self._get_mime(rel, fid)
            if mime != _GDOC_MIME:
                return self._read_legacy_md_bytes(fid)
            with self._service_lock:
                request = service.files().export_media(fileId=fid, mimeType=_MD_MIME)
                buf = io.BytesIO()
                downloader = MediaIoBaseDownload(buf, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk(num_retries=5)
            return buf.getvalue()

        with self._service_lock:
            request = service.files().get_media(fileId=fid, supportsAllDrives=True)
            buf = io.BytesIO()
            downloader = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _, done = downloader.next_chunk(num_retries=5)
        return buf.getvalue()

    def read_text(self, rel: str, *, encoding: str = "utf-8") -> str:
        return self.read_bytes(rel).decode(encoding)

    def write_bytes(self, rel: str, content: bytes) -> None:
        self._resolve_root_folder()
        rel = rel.strip("/")
        parent_rel = str(PurePosixPath(rel).parent)
        if parent_rel == ".":
            parent_rel = ""
        # Ensure parent exists.
        self.mkdir(parent_rel)
        parent_id = self._resolve_or_raise(parent_rel) if parent_rel else self.root_folder_id

        name = PurePosixPath(rel).name
        service = self._ensure_service()

        if _is_md_path(rel):
            content = _sanitize_markdown_upload(content)
            # Upload as markdown and let Drive convert to a Google Doc on import.
            # On update, the file ID is preserved so subsequent edits land in the
            # same gdoc and Drive records a new revision instead of creating a
            # duplicate sibling.
            media = MediaIoBaseUpload(io.BytesIO(content), mimetype=_MD_MIME, resumable=False)
            existing, same_name_files = self._resolve_md_child_for_write(parent_id, rel, name)
            existing_id = existing["id"] if existing else None
            written_id = existing_id
            with self._service_lock:
                if existing_id:
                    service.files().update(
                        fileId=existing_id,
                        media_body=media,
                        supportsAllDrives=True,
                    ).execute(num_retries=5)
                else:
                    created = service.files().create(
                        body={
                            "name": name,
                            "parents": [parent_id],
                            "mimeType": _GDOC_MIME,
                        },
                        media_body=media,
                        fields="id",
                        supportsAllDrives=True,
                    ).execute(num_retries=5)
                    written_id = created["id"]
            self._delete_legacy_md_siblings(rel, same_name_files, written_id)
            self._invalidate(rel)
            return

        media = MediaIoBaseUpload(io.BytesIO(content), mimetype="application/octet-stream", resumable=False)
        existing = self._resolve_unique_child_for_write(parent_id, rel, name)
        existing_id = existing["id"] if existing else None
        with self._service_lock:
            if existing_id:
                service.files().update(
                    fileId=existing_id,
                    media_body=media,
                    supportsAllDrives=True,
                ).execute(num_retries=5)
            else:
                service.files().create(
                    body={"name": name, "parents": [parent_id]},
                    media_body=media,
                    fields="id",
                    supportsAllDrives=True,
                ).execute(num_retries=5)
        self._invalidate(rel)

    def write_text(self, rel: str, content: str, *, encoding: str = "utf-8") -> None:
        self.write_bytes(rel, content.encode(encoding))

    def exists(self, rel: str) -> bool:
        return self._resolve(rel) is not None

    def is_dir(self, rel: str) -> bool:
        fid = self._resolve(rel)
        if fid is None:
            return False
        # Use cached metadata if we have it via parent's listing.
        parent_rel = str(PurePosixPath(rel).parent)
        if parent_rel == ".":
            parent_rel = ""
        children = self._dir_children.get(parent_rel)
        if children:
            name = PurePosixPath(rel).name
            for c in children:
                if c["name"] == name and c["id"] == fid:
                    return c.get("mimeType") == _FOLDER_MIME
        service = self._ensure_service()
        with self._service_lock:
            meta = service.files().get(fileId=fid, fields="mimeType", supportsAllDrives=True).execute()
        return meta.get("mimeType") == _FOLDER_MIME

    def list(self, rel: str, *, suffix: Optional[str] = None) -> List[str]:
        items = self._list_children(rel)
        names = [i["name"] for i in items]
        if suffix is not None:
            names = [n for n in names if n.lower().endswith(suffix.lower())]
        return sorted(names)

    def list_with_mtime(
        self, rel: str, *, recursive: bool = False
    ) -> List[Tuple[str, float]]:
        out: List[Tuple[str, float]] = []
        items = self._list_children(rel)
        for i in items:
            if i.get("mimeType") == _FOLDER_MIME:
                if recursive:
                    sub_rel = f"{rel}/{i['name']}" if rel else i["name"]
                    for name, mt in self.list_with_mtime(sub_rel, recursive=True):
                        out.append((f"{i['name']}/{name}", mt))
                continue
            out.append((i["name"], _parse_modtime(i.get("modifiedTime"))))
        return out

    def mtime(self, rel: str) -> Optional[float]:
        fid = self._resolve(rel)
        if fid is None:
            return None
        service = self._ensure_service()
        with self._service_lock:
            meta = service.files().get(fileId=fid, fields="modifiedTime", supportsAllDrives=True).execute()
        return _parse_modtime(meta.get("modifiedTime"))

    def set_mtime(self, rel: str, timestamp: float) -> None:
        fid = self._resolve_or_raise(rel)
        modified_time = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        service = self._ensure_service()
        with self._service_lock:
            service.files().update(
                fileId=fid,
                body={"modifiedTime": modified_time},
                fields="id,modifiedTime",
                supportsAllDrives=True,
            ).execute()
        self._invalidate(rel)

    def remove(self, rel: str) -> None:
        fid = self._resolve(rel)
        if fid is None:
            return
        service = self._ensure_service()
        try:
            with self._service_lock:
                service.files().delete(fileId=fid, supportsAllDrives=True).execute()
        except HttpError as e:
            if e.resp.status != 404:
                raise
        self._invalidate(rel)

    def rmtree(self, rel: str) -> None:
        # Drive's delete is recursive for folders.
        self.remove(rel)

    def mkdir(self, rel: str, *, parents: bool = True, exist_ok: bool = True) -> None:
        self._resolve_root_folder()
        rel = rel.strip("/")
        if not rel:
            return
        if self._resolve(rel) is not None:
            if exist_ok:
                return
            raise FileExistsError(rel)
        parent_rel = str(PurePosixPath(rel).parent)
        if parent_rel == ".":
            parent_rel = ""
        if parent_rel:
            if parents:
                self.mkdir(parent_rel)
            elif self._resolve(parent_rel) is None:
                raise FileNotFoundError(parent_rel)
        parent_id = self._resolve_or_raise(parent_rel) if parent_rel else self.root_folder_id
        service = self._ensure_service()
        with self._service_lock:
            created = service.files().create(
                body={
                    "name": PurePosixPath(rel).name,
                    "mimeType": _FOLDER_MIME,
                    "parents": [parent_id],
                },
                fields="id",
                supportsAllDrives=True,
            ).execute()
        self._invalidate(rel)
        self._path_to_id[rel] = created["id"]
        self._path_to_mime[rel] = _FOLDER_MIME

    # ---------- escape hatches ----------

    def refresh(self, rel: str = "") -> None:
        """Drop cached path/listing entries under rel. Forces fresh API calls."""
        if not rel:
            self._root_resolved = self._root_folder_spec == "root"
            self.root_folder_id = self._root_folder_spec
            self._path_to_id = {"": self.root_folder_id}
            self._path_to_mime = {"": _FOLDER_MIME}
            self._dir_children = {}
        else:
            self._invalidate(rel)

    def local_path(self, rel: str) -> Path:
        """Materialize to a local path under the cache dir; best-effort, no write-back."""
        local = self._local_cache_dir / rel
        if not self.exists(rel):
            local.mkdir(parents=True, exist_ok=True)
            return local
        if self.is_dir(rel):
            local.mkdir(parents=True, exist_ok=True)
            for name, _ in self.list_with_mtime(rel, recursive=True):
                child_rel = f"{rel}/{name}"
                child_local = local / name
                child_local.parent.mkdir(parents=True, exist_ok=True)
                try:
                    child_local.write_bytes(self.read_bytes(child_rel))
                except Exception:
                    pass
        else:
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(self.read_bytes(rel))
        return local
