"""
MirrorStorage — local filesystem working copy with Google Drive freshness.

Behavior:
  - read/list/exists/mtime: recursively pull-prune the relevant Drive folder
    once per process, then read locally.
  - write_*: write local first; for non-cache Markdown files, also upload to Drive
    as Google Docs. Existing Google Docs are updated in-place so Drive keeps
    revision history.
  - remove/rmtree: local only. Destructive Drive changes still require explicit
    sync tooling.
  - Paths whose first segment is in _LOCAL_PREFIXES skip Drive entirely.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import List, Optional, Tuple

from lib.storage import LocalStorage, _validate_rel
from lib.storage_gdrive import GoogleDriveStorage


# Path prefixes that must never trigger a Drive fallback or sync; they're caches
# or derivable data. Same idea as the old RoutedStorage._CACHE_PREFIXES.
_LOCAL_PREFIXES = ("datasets2md", "cache")


def _is_local_only(rel: str) -> bool:
    head = rel.split("/", 1)[0] if rel else ""
    return head in _LOCAL_PREFIXES


def _should_upload_markdown(rel: str) -> bool:
    return not _is_local_only(rel) and rel.lower().endswith(".md")


def _same_mtime(a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= 1.0


class MirrorStorage:
    def __init__(self, local: LocalStorage, drive: GoogleDriveStorage):
        self.local = local
        self.drive = drive
        self._synced_dirs: set[str] = set()

    # ---------- internal: lazy recursive pull ----------

    def _parent_dir(self, rel: str) -> str:
        parent = str(PurePosixPath(rel).parent)
        return "" if parent == "." else parent

    def _remove_empty_parents(self, rel: str, stop_rel: str) -> None:
        base = Path(self.local.base)
        stop = base / stop_rel if stop_rel else base
        parent = (base / rel).parent
        while parent != stop and parent != base and parent.exists():
            try:
                parent.rmdir()
            except OSError:
                return
            parent = parent.parent

    def _ensure_drive_dir_synced(self, rel: str) -> None:
        """Recursively mirror one Drive folder into local, including deletions."""
        rel = _validate_rel(rel)
        rel = rel.strip("/")
        if _is_local_only(rel) or rel in self._synced_dirs:
            return

        if not self.drive.exists(rel):
            if rel and self.local.exists(rel):
                if self.local.is_dir(rel):
                    self.local.rmtree(rel)
                else:
                    self.local.remove(rel)
            self._synced_dirs.add(rel)
            return

        if not self.drive.is_dir(rel):
            self._ensure_drive_dir_synced(self._parent_dir(rel))
            return

        drive_files = dict(self.drive.list_with_mtime(rel, recursive=True))
        local_files = dict(self.local.list_with_mtime(rel, recursive=True))

        for name, source_mtime in drive_files.items():
            child = f"{rel}/{name}" if rel else name
            if self.local.exists(child) and _same_mtime(self.local.mtime(child), source_mtime):
                continue
            content = self.drive.read_bytes(child)
            self.local.write_bytes(child, content)
            self.local.set_mtime(child, source_mtime)

        for name in sorted(set(local_files) - set(drive_files)):
            child = f"{rel}/{name}" if rel else name
            self.local.remove(child)
            self._remove_empty_parents(child, rel)

        self._synced_dirs.add(rel)

    def _ensure_parent_synced(self, rel: str) -> None:
        rel = _validate_rel(rel)
        if _is_local_only(rel):
            return
        rel = rel.strip("/")
        parent = self._parent_dir(rel)
        if rel in self._synced_dirs or parent in self._synced_dirs:
            return
        if self.drive.exists(rel) and self.drive.is_dir(rel):
            self._ensure_drive_dir_synced(rel)
            return
        self._ensure_drive_dir_synced(parent)

    # ---------- Storage API ----------

    def read_bytes(self, rel: str) -> bytes:
        rel = _validate_rel(rel)
        self._ensure_parent_synced(rel)
        return self.local.read_bytes(rel)

    def read_text(self, rel: str, *, encoding: str = "utf-8") -> str:
        return self.read_bytes(rel).decode(encoding)

    def write_bytes(self, rel: str, content: bytes) -> None:
        rel = _validate_rel(rel)
        self.local.write_bytes(rel, content)
        if _should_upload_markdown(rel):
            self.drive.write_bytes(rel, content)

    def write_text(self, rel: str, content: str, *, encoding: str = "utf-8") -> None:
        rel = _validate_rel(rel)
        self.local.write_text(rel, content, encoding=encoding)
        if _should_upload_markdown(rel):
            self.drive.write_bytes(rel, content.encode(encoding))

    def exists(self, rel: str) -> bool:
        rel = _validate_rel(rel)
        self._ensure_parent_synced(rel)
        return self.local.exists(rel)

    def is_dir(self, rel: str) -> bool:
        rel = _validate_rel(rel)
        self._ensure_parent_synced(rel)
        return self.local.is_dir(rel)

    def list(self, rel: str, *, suffix: Optional[str] = None) -> List[str]:
        rel = _validate_rel(rel)
        self._ensure_drive_dir_synced(rel)
        return self.local.list(rel, suffix=suffix)

    def list_with_mtime(
        self, rel: str, *, recursive: bool = False
    ) -> List[Tuple[str, float]]:
        rel = _validate_rel(rel)
        self._ensure_drive_dir_synced(rel)
        return self.local.list_with_mtime(rel, recursive=recursive)

    def mtime(self, rel: str) -> Optional[float]:
        rel = _validate_rel(rel)
        self._ensure_parent_synced(rel)
        return self.local.mtime(rel)

    def set_mtime(self, rel: str, timestamp: float) -> None:
        rel = _validate_rel(rel)
        self.local.set_mtime(rel, timestamp)
        if _should_upload_markdown(rel):
            self.drive.set_mtime(rel, timestamp)

    def remove(self, rel: str) -> None:
        self.local.remove(rel)

    def rmtree(self, rel: str) -> None:
        self.local.rmtree(rel)

    def mkdir(self, rel: str, *, parents: bool = True, exist_ok: bool = True) -> None:
        self.local.mkdir(rel, parents=parents, exist_ok=exist_ok)

    def refresh(self, rel: str = "") -> None:
        rel = _validate_rel(rel) if rel else ""
        self.drive.refresh(rel)
        if not rel:
            self._synced_dirs.clear()
            return
        rel = rel.strip("/")
        self._synced_dirs = {
            synced
            for synced in self._synced_dirs
            if synced != rel and not synced.startswith(f"{rel}/")
        }

    def local_path(self, rel: str) -> Path:
        rel = _validate_rel(rel)
        if self.local.exists(rel) and self.local.is_dir(rel):
            self._ensure_drive_dir_synced(rel)
        else:
            self._ensure_parent_synced(rel)
        return self.local.local_path(rel)

    def _hydrate_if_missing(self, rel: str) -> bool:
        """Backward-compatible test helper; normal reads sync parent dirs."""
        rel = _validate_rel(rel)
        self._ensure_parent_synced(rel)
        return self.local.exists(rel)

    def _hydrate_dir(self, rel: str, *, recursive: bool = False) -> None:
        """Backward-compatible test helper; syncs recursively regardless of flag."""
        try:
            self._ensure_drive_dir_synced(rel)
        except Exception:
            return
