from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from .types import SnapshotEntry
from .util import clean_rel, is_excluded, is_hidden_rel, sha256_file


class LocalTree:
    def __init__(self, root: str | os.PathLike, *, exclude: list[str] | None = None):
        self.root = Path(root).expanduser().resolve()
        self.exclude = exclude or []
        self.root.mkdir(parents=True, exist_ok=True)

    def _full(self, rel: str) -> Path:
        rel = clean_rel(rel)
        return self.root / rel

    def scan(self) -> dict[str, SnapshotEntry]:
        out: dict[str, SnapshotEntry] = {}
        for path in sorted(self.root.rglob("*")):
            rel = path.relative_to(self.root).as_posix()
            if is_hidden_rel(rel) or is_excluded(rel, self.exclude):
                continue
            if path.is_symlink():
                continue
            if path.is_dir():
                out[rel] = SnapshotEntry(path=rel, type="folder", mtime=path.stat().st_mtime)
            elif path.is_file():
                stat = path.stat()
                out[rel] = SnapshotEntry(
                    path=rel,
                    type="file",
                    sha256=sha256_file(path),
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                )
        return out

    def read_bytes(self, rel: str) -> bytes:
        return self._full(rel).read_bytes()

    def write_bytes_atomic(self, rel: str, content: bytes) -> None:
        target = self._full(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
            os.replace(tmp_name, target)
        finally:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass

    def mkdir(self, rel: str) -> None:
        self._full(rel).mkdir(parents=True, exist_ok=True)

    def remove(self, rel: str) -> None:
        path = self._full(rel)
        if path.is_dir():
            shutil.rmtree(path)
            return
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def prune_empty_parents(self, rel: str) -> None:
        parent = self._full(rel).parent
        while parent != self.root and parent.exists():
            try:
                parent.rmdir()
            except OSError:
                return
            parent = parent.parent
