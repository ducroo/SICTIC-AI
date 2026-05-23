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
from datetime import datetime
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
_FIELDS = "id,name,mimeType,modifiedTime,size"


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
        base_dir: Optional[str] = None,
        local_cache_dir: Optional[str] = None,
    ):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.root_folder_id = root_folder_id
        self.base_dir = base_dir
        self._local_cache_dir = Path(
            local_cache_dir
            or os.path.expanduser("~/.cache/sictic/gdrive-materialized")
        )
        self._local_cache_dir.mkdir(parents=True, exist_ok=True)

        self._service = None
        self._service_lock = threading.Lock()

        # rel-path -> Drive file ID (None means known-nonexistent)
        self._path_to_id: Dict[str, Optional[str]] = {"": root_folder_id}
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

    # ---------- path resolution ----------

    def _resolve(self, rel: str) -> Optional[str]:
        """Return the Drive file ID for rel, or None if it doesn't exist."""
        # Use the common path validator to strip any absolute base_dir prefixes
        from lib.storage import _validate_rel
        rel = _validate_rel(rel, base_dir=self.base_dir)
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
        # Drive permits same-name siblings; take the first deterministically.
        files.sort(key=lambda f: f["id"])
        self._path_to_id[rel] = files[0]["id"]
        return files[0]["id"]

    def _resolve_or_raise(self, rel: str) -> str:
        fid = self._resolve(rel)
        if fid is None:
            raise FileNotFoundError(rel)
        return fid

    def _list_children(self, rel: str) -> List[dict]:
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
            self._path_to_id[f"{prefix}{item['name']}"] = item["id"]
        return items

    def _invalidate(self, rel: str) -> None:
        rel = rel.strip("/")
        self._path_to_id.pop(rel, None)
        parent = str(PurePosixPath(rel).parent) if rel else ""
        if parent == ".":
            parent = ""
        self._dir_children.pop(parent, None)
        # Drop any descendant cache entries.
        prefix = f"{rel}/" if rel else ""
        for k in [k for k in self._path_to_id if k.startswith(prefix)]:
            self._path_to_id.pop(k, None)
        for k in [k for k in self._dir_children if k == rel or k.startswith(prefix)]:
            self._dir_children.pop(k, None)

    # ---------- Storage API ----------

    def read_bytes(self, rel: str) -> bytes:
        fid = self._resolve_or_raise(rel)
        service = self._ensure_service()
        with self._service_lock:
            request = service.files().get_media(fileId=fid, supportsAllDrives=True)
            buf = io.BytesIO()
            downloader = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        return buf.getvalue()

    def read_text(self, rel: str, *, encoding: str = "utf-8") -> str:
        return self.read_bytes(rel).decode(encoding)

    def write_bytes(self, rel: str, content: bytes) -> None:
        rel = rel.strip("/")
        parent_rel = str(PurePosixPath(rel).parent)
        if parent_rel == ".":
            parent_rel = ""
        # Ensure parent exists.
        self.mkdir(parent_rel)
        parent_id = self._resolve_or_raise(parent_rel) if parent_rel else self.root_folder_id

        name = PurePosixPath(rel).name
        service = self._ensure_service()
        media = MediaIoBaseUpload(io.BytesIO(content), mimetype="application/octet-stream", resumable=False)
        existing_id = self._resolve(rel)
        with self._service_lock:
            if existing_id:
                service.files().update(
                    fileId=existing_id,
                    media_body=media,
                    supportsAllDrives=True,
                ).execute()
            else:
                service.files().create(
                    body={"name": name, "parents": [parent_id]},
                    media_body=media,
                    fields="id",
                    supportsAllDrives=True,
                ).execute()
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

    # ---------- escape hatches ----------

    def refresh(self, rel: str = "") -> None:
        """Drop cached path/listing entries under rel. Forces fresh API calls."""
        if not rel:
            self._path_to_id = {"": self.root_folder_id}
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
