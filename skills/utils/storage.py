"""
Storage abstraction for skills that read/write data under $GDRIVE_MOUNT.

Skills should call `get_storage().write_text("insights/foo/bar.md", content)`
instead of `open(os.path.join(gdrive_mount, "insights", "foo", "bar.md"), "w")`.

Two backends:
  - LocalStorage(base_path):     today's behavior — reads/writes the FUSE mount
                                 (or any local dir).
  - GoogleDriveStorage(...):     Google Drive via the native Drive API
                                 (see storage_gdrive.py). No rclone in the loop.

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


def _validate_rel(rel: str) -> None:
    if rel.startswith("/"):
        raise ValueError(f"Storage paths must be relative, got: {rel!r}")
    parts = Path(rel).parts
    if ".." in parts:
        raise ValueError(f"Storage paths must not contain '..': {rel!r}")


class LocalStorage:
    """Backs a Storage by a directory on the local filesystem."""

    def __init__(self, base_path: str | os.PathLike):
        self.base = Path(base_path)

    def _full(self, rel: str) -> Path:
        _validate_rel(rel)
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
_CACHE_PREFIXES = ("datasets_parsed",)


class RoutedStorage:
    """Dispatches Storage operations to drive vs cache based on the path prefix."""

    def __init__(self, drive: Storage, cache: Storage):
        self.drive = drive
        self.cache = cache

    def _pick(self, rel: str) -> Storage:
        _validate_rel(rel)
        head = rel.split("/", 1)[0]
        return self.cache if head in _CACHE_PREFIXES else self.drive

    def read_text(self, rel: str, *, encoding: str = "utf-8") -> str:
        return self._pick(rel).read_text(rel, encoding=encoding)

    def write_text(self, rel: str, content: str, *, encoding: str = "utf-8") -> None:
        self._pick(rel).write_text(rel, content, encoding=encoding)

    def read_bytes(self, rel: str) -> bytes:
        return self._pick(rel).read_bytes(rel)

    def write_bytes(self, rel: str, content: bytes) -> None:
        self._pick(rel).write_bytes(rel, content)

    def exists(self, rel: str) -> bool:
        return self._pick(rel).exists(rel)

    def is_dir(self, rel: str) -> bool:
        return self._pick(rel).is_dir(rel)

    def list(self, rel: str, *, suffix: Optional[str] = None) -> List[str]:
        return self._pick(rel).list(rel, suffix=suffix)

    def list_with_mtime(
        self, rel: str, *, recursive: bool = False
    ) -> List[Tuple[str, float]]:
        return self._pick(rel).list_with_mtime(rel, recursive=recursive)

    def mtime(self, rel: str) -> Optional[float]:
        return self._pick(rel).mtime(rel)

    def remove(self, rel: str) -> None:
        self._pick(rel).remove(rel)

    def rmtree(self, rel: str) -> None:
        self._pick(rel).rmtree(rel)

    def mkdir(self, rel: str, *, parents: bool = True, exist_ok: bool = True) -> None:
        self._pick(rel).mkdir(rel, parents=parents, exist_ok=exist_ok)

    def refresh(self, rel: str = "") -> None:
        # If rel is empty, refresh both backends. Otherwise route by prefix.
        if not rel:
            self.drive.refresh("")
            self.cache.refresh("")
            return
        self._pick(rel).refresh(rel)

    def local_path(self, rel: str):
        """Delegates to the picked backend; backend must implement local_path."""
        return self._pick(rel).local_path(rel)


# ---------- Factory ----------

_storage_singleton: Optional[Storage] = None


def get_storage() -> Storage:
    """
    Returns the process-wide Storage instance.

    Mount mode (default):  LocalStorage($GDRIVE_MOUNT) — reads/writes the
                           FUSE mount provided by `rclone mount`.

    API mode (GDRIVE_USE_API=1):  RoutedStorage with GoogleDriveStorage for
                           drive paths and LocalStorage($CACHE_DIR) for caches.
                           No rclone process required.

    Credentials for API mode default to:
        ~/.openclaw/gdrive-ops-credentials.json   (Desktop-app OAuth client)
        ~/.openclaw/gdrive-ops-token.json         (refresh token cache)
    Override with GDRIVE_CREDENTIALS / GDRIVE_TOKEN env vars.
    """
    global _storage_singleton
    if _storage_singleton is not None:
        return _storage_singleton

    if os.getenv("GDRIVE_USE_API") == "1":
        from skills.utils.storage_gdrive import GoogleDriveStorage

        credentials_path = os.getenv(
            "GDRIVE_CREDENTIALS",
            os.path.expanduser("~/.openclaw/gdrive-ops-credentials.json"),
        )
        token_path = os.getenv(
            "GDRIVE_TOKEN",
            os.path.expanduser("~/.openclaw/gdrive-ops-token.json"),
        )
        drive: Storage = GoogleDriveStorage(
            credentials_path=credentials_path,
            token_path=token_path,
            root_folder_id=os.getenv("GDRIVE_ROOT_FOLDER_ID", "root"),
        )
        cache_dir = os.getenv("CACHE_DIR") or os.path.expanduser("~/.cache/sictic")
        os.makedirs(cache_dir, exist_ok=True)
        _storage_singleton = RoutedStorage(drive=drive, cache=LocalStorage(cache_dir))
    else:
        mount = os.environ["GDRIVE_MOUNT"]
        _storage_singleton = LocalStorage(mount)

    return _storage_singleton


def reset_storage_singleton() -> None:
    """For tests — drop the cached singleton so env changes take effect."""
    global _storage_singleton
    _storage_singleton = None
