"""
Local storage abstraction for skills that read/write data.

Skills should use domain helpers such as `InsightFile` for managed artifacts,
and pass relative paths to Storage for ordinary local data.

RoutedStorage dispatches between the configured application-storage directory
and repository-local runtime data. Optional external synchronization operates
on those local files and is not a Storage backend.
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
    def set_mtime(self, rel: str, timestamp: float) -> None: ...
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

    def set_mtime(self, rel: str, timestamp: float) -> None:
        p = self._full(rel)
        os.utime(p, (timestamp, timestamp))

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
    # Some callers, such as Docling, need a real OS path.
    def local_path(self, rel: str) -> Path:
        return self._full(rel)


# ---------- Routing ----------

# Paths whose first segment matches these always go to repository-local storage,
# even when canonical storage is remote or mirrored.
_LOCAL_PREFIXES = ("cache", "docling_data")


class RoutedStorage:
    """Dispatch Storage paths between two local filesystem roots."""

    def __init__(self, primary: Storage, cache: Storage):
        self.primary = primary
        self.cache = cache

    def _pick(self, rel: str) -> Tuple[str, Storage]:
        """Normalize rel and select the backing storage. Returns (clean_rel, store)."""
        rel = _validate_rel(rel)
        head = rel.split("/", 1)[0]
        store = self.cache if head in _LOCAL_PREFIXES else self.primary
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

    def set_mtime(self, rel: str, timestamp: float) -> None:
        rel, store = self._pick(rel)
        store.set_mtime(rel, timestamp)

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
            self.primary.refresh("")
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
    Return the process-wide local Storage instance.

    Application data uses LOCAL_STORAGE_PATH. Repository-local runtime data
    under cache/ and docling_data/ uses LOCAL_DATA_PATH.
    """
    global _storage_singleton
    if _storage_singleton is not None:
        return _storage_singleton

    from lib.infrastructure.configuration import get_env_var
    repo_path = os.environ.get("REPO_PATH")
    local_data_path = (
        os.environ.get("LOCAL_DATA_PATH")
        or repo_path
        or os.path.expanduser("~/.local/share/sictic")
    )
    if not os.path.isabs(local_data_path):
        raise ValueError(f"LOCAL_DATA_PATH must be an absolute path, got: {local_data_path}")
    os.makedirs(local_data_path, exist_ok=True)
    local_data = LocalStorage(local_data_path)

    base_dir = get_env_var("LOCAL_STORAGE_PATH")
    if not base_dir.startswith("/"):
        raise ValueError(
            f"LOCAL_STORAGE_PATH must be an absolute path, got: {base_dir}"
        )
    os.makedirs(base_dir, exist_ok=True)
    _storage_singleton = RoutedStorage(
        primary=LocalStorage(base_dir),
        cache=local_data,
    )

    return _storage_singleton


def reset_storage_singleton() -> None:
    """For tests — drop the cached singleton so env changes take effect."""
    global _storage_singleton
    _storage_singleton = None
