"""
MirrorStorage — local filesystem is the working copy, Google Drive is the
backup/source-of-truth that gets explicitly pulled and pushed.

Behavior:
  - read_*: try local; on miss, fetch from Drive, write to local mirror, return.
  - write_*, mkdir, remove, rmtree: local only. Drive is never mutated at runtime.
  - exists/is_dir/list*/mtime: local only. After a pull the mirror is the truth.
  - Paths whose first segment is in _LOCAL_PREFIXES skip the Drive fallback entirely
    (used for caches that should never round-trip to Drive — datasets2md/ etc.).

Drive mutations happen exclusively through scripts/gdrive_sync.py (push direction).
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path, PurePosixPath
from typing import List, Optional, Tuple

from lib.storage import LocalStorage, Storage, _validate_rel
from lib.storage_gdrive import GoogleDriveStorage


# Path prefixes that must never trigger a Drive fallback or sync; they're caches
# or derivable data. Same idea as the old RoutedStorage._CACHE_PREFIXES.
_LOCAL_PREFIXES = ("datasets2md",)


def _is_local_only(rel: str) -> bool:
    head = rel.split("/", 1)[0] if rel else ""
    return head in _LOCAL_PREFIXES


class MirrorStorage:
    def __init__(self, local: LocalStorage, drive: GoogleDriveStorage):
        self.local = local
        self.drive = drive

    # ---------- internal: hydrate-on-miss ----------

    def _hydrate_if_missing(self, rel: str) -> bool:
        """Ensure rel exists locally, fetching from Drive on miss.

        Returns True if the file is now available locally, False if it's
        absent on both sides. Never raises for "not found".
        """
        rel = _validate_rel(rel)
        if self.local.exists(rel):
            return True
        if _is_local_only(rel):
            return False
        # Try Drive. If it doesn't exist there either, give up silently —
        # callers that need exists() to be true should check exists() first.
        if not self.drive.exists(rel):
            return False
        # Drive's read_bytes already handles gdoc -> markdown export for .md
        # paths, so the bytes we write locally are already in canonical form.
        try:
            content = self.drive.read_bytes(rel)
        except Exception:
            return False
        self.local.write_bytes(rel, content)
        return True

    # ---------- Storage API ----------

    def read_bytes(self, rel: str) -> bytes:
        rel = _validate_rel(rel)
        if not self.local.exists(rel) and not _is_local_only(rel):
            self._hydrate_if_missing(rel)
        return self.local.read_bytes(rel)

    def read_text(self, rel: str, *, encoding: str = "utf-8") -> str:
        return self.read_bytes(rel).decode(encoding)

    def write_bytes(self, rel: str, content: bytes) -> None:
        self.local.write_bytes(rel, content)

    def write_text(self, rel: str, content: str, *, encoding: str = "utf-8") -> None:
        self.local.write_text(rel, content, encoding=encoding)

    def exists(self, rel: str) -> bool:
        rel = _validate_rel(rel)
        if self.local.exists(rel):
            return True
        if _is_local_only(rel):
            return False
        # Lazy: only consult Drive if local is empty. Avoids a Drive call on
        # the common path where the mirror is up-to-date.
        return self.drive.exists(rel)

    def is_dir(self, rel: str) -> bool:
        rel = _validate_rel(rel)
        if self.local.exists(rel):
            return self.local.is_dir(rel)
        if _is_local_only(rel):
            return False
        return self.drive.is_dir(rel)

    def list(self, rel: str, *, suffix: Optional[str] = None) -> List[str]:
        rel = _validate_rel(rel)
        # If the directory doesn't exist locally but does on Drive, hydrate it
        # so list() returns a stable answer regardless of whether sync has run.
        if not self.local.exists(rel) and not _is_local_only(rel):
            self._hydrate_dir(rel)
        return self.local.list(rel, suffix=suffix)

    def list_with_mtime(
        self, rel: str, *, recursive: bool = False
    ) -> List[Tuple[str, float]]:
        rel = _validate_rel(rel)
        if not self.local.exists(rel) and not _is_local_only(rel):
            self._hydrate_dir(rel, recursive=recursive)
        return self.local.list_with_mtime(rel, recursive=recursive)

    def _hydrate_dir(self, rel: str, *, recursive: bool = False) -> None:
        """Materialize a Drive subtree into the local mirror. Best-effort."""
        if _is_local_only(rel):
            return
        if not self.drive.exists(rel):
            return
        try:
            entries = self.drive.list_with_mtime(rel, recursive=recursive)
        except Exception:
            return
        for name, _ in entries:
            child = f"{rel}/{name}" if rel else name
            if self.local.exists(child):
                continue
            try:
                content = self.drive.read_bytes(child)
            except Exception:
                continue
            self.local.write_bytes(child, content)

    def mtime(self, rel: str) -> Optional[float]:
        rel = _validate_rel(rel)
        if not self.local.exists(rel) and not _is_local_only(rel):
            self._hydrate_if_missing(rel)
        return self.local.mtime(rel)

    def remove(self, rel: str) -> None:
        self.local.remove(rel)

    def rmtree(self, rel: str) -> None:
        self.local.rmtree(rel)

    def mkdir(self, rel: str, *, parents: bool = True, exist_ok: bool = True) -> None:
        self.local.mkdir(rel, parents=parents, exist_ok=exist_ok)

    def refresh(self, rel: str = "") -> None:
        # Local filesystem is authoritative; only refresh the Drive caches so
        # that the next miss hits Drive with fresh metadata.
        self.drive.refresh(rel)

    def local_path(self, rel: str) -> Path:
        rel = _validate_rel(rel)
        if not self.local.exists(rel) and not _is_local_only(rel):
            self._hydrate_if_missing(rel)
        return self.local.local_path(rel)
