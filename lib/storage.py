"""
Storage abstraction for skills that read/write data.

Skills should call `get_storage().write_text("insights/foo/bar.md", content)`
instead of passing absolute paths.

Two backends:
  - LocalStorage: reads/writes a local directory.
  - GoogleDriveStorage: Google Drive via the native Drive API.

RoutedStorage dispatches by path prefix so caches always stay local even
when the source/output backend is remote.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import List, Optional, Protocol, Tuple


class Storage(Protocol):
    def read_text(self, rel: str, *, encoding: str = "utf-8") -> str: ...
    def write_text(self, rel: str, content: str, *, encoding: str = "utf-8") -> None: ...
    def read_bytes(self, rel: str) -> bytes: ...
    def write_bytes(self, rel: str, content: bytes) -> None: ...
    def exists(self, rel: str) -> bool: ...
    def is_dir(self, rel: str) -> bool: ...
    def list(self, rel: str, *, suffix: Optional[str] = None) -> List[str]: ...
    def list_with_mtime(
        self, rel: str, *, recursive: bool = False
    ) -> List[Tuple[str, float]]: ...
    def mtime(self, rel: str) -> Optional[float]: ...
    def remove(self, rel: str) -> None: ...
    def rmtree(self, rel: str) -> None: ...
    def mkdir(self, rel: str, *, parents: bool = True, exist_ok: bool = True) -> None: ...
    def refresh(self, rel: str = "") -> None: ...


def _validate_rel(rel: str) -> str:
    """Return a clean relative storage path.

    Raises ValueError if an absolute path or a path containing '..' is passed.
    """
    if rel.startswith("/"):
        raise ValueError(f"Storage paths must be strictly relative, got: {rel!r}")
    parts = Path(rel).parts
    if ".." in parts:
        raise ValueError(f"Storage paths must not contain '..': {rel!r}")
    return rel


class LocalStorage:
    """Backs a Storage by a directory on the local filesystem."""

    def __init__(self, base_path: str | os.PathLike):
        self.base = Path(base_path)

    def _full(self, rel: str) -> Path:
        rel = _validate_rel(rel)
        return self.base / rel

    def read_text(self, rel: str, *, encoding: str = "utf-8") -> str:
        return self._full(rel).read_text(encoding=encoding)

    def write_text(self, rel: str, content: str, *, encoding: str = "utf-8") -> None:
        p = self._full(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)

    def read_bytes(self, rel: str) -> bytes:
        return self._full(rel).read_bytes()

    def write_bytes(self, rel: str, content: bytes) -> None:
        p = self._full(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)

    def exists(self, rel: str) -> bool:
        return self._full(rel).exists()

    def is_dir(self, rel: str) -> bool:
        return self._full(rel).is_dir()

    def list(self, rel: str, *, suffix: Optional[str] = None) -> List[str]:
        p = self._full(rel)
        if not p.is_dir():
            return []
        names = [item.name for item in p.iterdir()]
        if suffix is not None:
            names = [n for n in names if n.lower().endswith(suffix.lower())]
        return sorted(names)

    def list_with_mtime(
        self, rel: str, *, recursive: bool = False
    ) -> List[Tuple[str, float]]:
        p = self._full(rel)
        if not p.is_dir():
            return []
        out: List[Tuple[str, float]] = []
        if recursive:
            for f in p.rglob("*"):
                if f.is_file():
                    out.append((str(f.relative_to(p)), f.stat().st_mtime))
        else:
            for f in p.iterdir():
                if f.is_file():
                    out.append((f.name, f.stat().st_mtime))
        return out

    def mtime(self, rel: str) -> Optional[float]:
        p = self._full(rel)
        try:
            return p.stat().st_mtime
        except FileNotFoundError:
            return None

    def remove(self, rel: str) -> None:
        try:
            self._full(rel).unlink()
        except FileNotFoundError:
            pass

    def rmtree(self, rel: str) -> None:
        p = self._full(rel)
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)

    def mkdir(self, rel: str, *, parents: bool = True, exist_ok: bool = True) -> None:
        self._full(rel).mkdir(parents=parents, exist_ok=exist_ok)

    def refresh(self, rel: str = "") -> None:
        # No-op: the filesystem is authoritative. (FUSE-mount staleness is
        # handled by the mount process itself, not the storage layer.)
        return

    # --- escape hatch ---
    # Some callers (docling upload, LinkedInAdapter) need a real OS path.
    # In LocalStorage this is trivial; GoogleDriveStorage materializes to a temp dir.
    def local_path(self, rel: str) -> Path:
        return self._full(rel)


class MockStorage(LocalStorage):
    """Identical to LocalStorage; explicit name signals 'this is for tests'."""

    pass


# ---------- Routing ----------

# Paths whose first segment matches these always go to the local cache,
# even when the main storage is remote. Caches are re-derivable.
_CACHE_PREFIXES = ("datasets2md",)


class RoutedStorage:
    """Dispatches Storage operations to drive vs cache based on the path prefix."""

    def __init__(self, drive: Storage, cache: Storage):
        self.drive = drive
        self.cache = cache

    def _pick(self, rel: str) -> Tuple[str, Storage]:
        """Normalize rel and select the backing storage. Returns (clean_rel, store)."""
        rel = _validate_rel(rel)
        head = rel.split("/", 1)[0]
        store = self.cache if head in _CACHE_PREFIXES else self.drive
        return rel, store

    def read_text(self, rel: str, *, encoding: str = "utf-8") -> str:
        rel, store = self._pick(rel)
        return store.read_text(rel, encoding=encoding)

    def write_text(self, rel: str, content: str, *, encoding: str = "utf-8") -> None:
        rel, store = self._pick(rel)
        store.write_text(rel, content, encoding=encoding)

    def read_bytes(self, rel: str) -> bytes:
        rel, store = self._pick(rel)
        return store.read_bytes(rel)

    def write_bytes(self, rel: str, content: bytes) -> None:
        rel, store = self._pick(rel)
        store.write_bytes(rel, content)

    def exists(self, rel: str) -> bool:
        rel, store = self._pick(rel)
        return store.exists(rel)

    def is_dir(self, rel: str) -> bool:
        rel, store = self._pick(rel)
        return store.is_dir(rel)

    def list(self, rel: str, *, suffix: Optional[str] = None) -> List[str]:
        rel, store = self._pick(rel)
        return store.list(rel, suffix=suffix)

    def list_with_mtime(
        self, rel: str, *, recursive: bool = False
    ) -> List[Tuple[str, float]]:
        rel, store = self._pick(rel)
        return store.list_with_mtime(rel, recursive=recursive)

    def mtime(self, rel: str) -> Optional[float]:
        rel, store = self._pick(rel)
        return store.mtime(rel)

    def remove(self, rel: str) -> None:
        rel, store = self._pick(rel)
        store.remove(rel)

    def rmtree(self, rel: str) -> None:
        rel, store = self._pick(rel)
        store.rmtree(rel)

    def mkdir(self, rel: str, *, parents: bool = True, exist_ok: bool = True) -> None:
        rel, store = self._pick(rel)
        store.mkdir(rel, parents=parents, exist_ok=exist_ok)

    def refresh(self, rel: str = "") -> None:
        # If rel is empty, refresh both backends. Otherwise route by prefix.
        if not rel:
            self.drive.refresh("")
            self.cache.refresh("")
            return
        rel, store = self._pick(rel)
        store.refresh(rel)

    def local_path(self, rel: str):
        """Delegates to the picked backend; backend must implement local_path."""
        rel, store = self._pick(rel)
        return store.local_path(rel)


# ---------- Factory ----------

_storage_singleton: Optional[Storage] = None


def get_storage() -> Storage:
    """
    Returns the process-wide Storage instance based on .env configuration.

    STORAGE_PROVIDER="local":  LocalStorage(STORAGE_PATH)
    STORAGE_PROVIDER="google": RoutedStorage with GoogleDriveStorage(STORAGE_PATH)
                               for drive paths and LocalStorage($REPO_DIR/cache) for caches.
    STORAGE_PROVIDER="hybrid": MirrorStorage — local mirror at STORAGE_MIRROR_DIR,
                               Drive as read-fallback and explicit sync target.
                               Writes go local-only; use scripts/gdrive_sync.py
                               to push changes back. STORAGE_PATH is the Drive
                               root folder ID used for read-fallback.
    """
    global _storage_singleton
    if _storage_singleton is not None:
        return _storage_singleton

    from lib.env import get_env_var
    provider = os.environ.get("STORAGE_PROVIDER", "local").lower()

    if provider == "google":
        from lib.storage_gdrive import GoogleDriveStorage

        credentials_path = os.environ.get("GDRIVE_CREDENTIALS") or os.path.expanduser("~/.openclaw/gdrive-ops-credentials.json")
        token_path = os.environ.get("GDRIVE_TOKEN") or os.path.expanduser("~/.openclaw/gdrive-ops-token.json")

        # In Google mode, STORAGE_PATH acts as the root folder ID (defaults to "root")
        root_folder_id = get_env_var("STORAGE_PATH") or "root"

        drive: Storage = GoogleDriveStorage(
            credentials_path=credentials_path,
            token_path=token_path,
            root_folder_id=root_folder_id
        )
        repo_dir = os.environ.get("REPO_DIR")
        cache_dir = os.path.join(repo_dir, "cache") if repo_dir else os.path.expanduser("~/.cache/sictic")
        os.makedirs(cache_dir, exist_ok=True)
        _storage_singleton = RoutedStorage(drive=drive, cache=LocalStorage(cache_dir))
    elif provider == "hybrid":
        from lib.storage_gdrive import GoogleDriveStorage
        from lib.storage_mirror import MirrorStorage

        mirror_dir = get_env_var("STORAGE_MIRROR_DIR")
        if not mirror_dir.startswith("/"):
            raise ValueError(
                f"STORAGE_MIRROR_DIR must be an absolute path, got: {mirror_dir}"
            )
        os.makedirs(mirror_dir, exist_ok=True)

        credentials_path = os.environ.get("GDRIVE_CREDENTIALS") or os.path.expanduser("~/.openclaw/gdrive-ops-credentials.json")
        token_path = os.environ.get("GDRIVE_TOKEN") or os.path.expanduser("~/.openclaw/gdrive-ops-token.json")
        root_folder_id = os.environ.get("STORAGE_PATH") or "root"

        drive = GoogleDriveStorage(
            credentials_path=credentials_path,
            token_path=token_path,
            root_folder_id=root_folder_id,
        )
        _storage_singleton = MirrorStorage(local=LocalStorage(mirror_dir), drive=drive)
    else:
        # Local mode requires an absolute path
        base_dir = get_env_var("STORAGE_PATH")
        if not base_dir.startswith("/"):
            raise ValueError(f"STORAGE_PATH must be an absolute path when provider is 'local', got: {base_dir}")
        _storage_singleton = LocalStorage(base_dir)

    return _storage_singleton


def reset_storage_singleton() -> None:
    """For tests — drop the cached singleton so env changes take effect."""
    global _storage_singleton
    _storage_singleton = None
