from __future__ import annotations

import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .types import SnapshotEntry
from .util import clean_rel, is_excluded, is_hidden_rel, sha256_file


_HASH_WORKERS = min(8, os.cpu_count() or 4)


def _hashed_entry(item: tuple[str, Path, os.stat_result]) -> tuple[str, SnapshotEntry]:
    rel, path, stat = item
    digest = sha256_file(path)
    return rel, SnapshotEntry(
        path=rel,
        type="file",
        sha256=digest,
        size=stat.st_size,
        mtime=stat.st_mtime,
        local_sha256=digest,
        local_size=stat.st_size,
        local_mtime_ns=stat.st_mtime_ns,
    )


class LocalTree:
    def __init__(self, root: str | os.PathLike, *, exclude: list[str] | None = None):
        self.root = Path(root).expanduser().resolve()
        self.exclude = exclude or []
        self.root.mkdir(parents=True, exist_ok=True)

    def _full(self, rel: str) -> Path:
        rel = clean_rel(rel)
        return self.root / rel

    def scan(
        self,
        baseline: dict[str, SnapshotEntry] | None = None,
    ) -> dict[str, SnapshotEntry]:
        baseline = baseline or {}
        out: dict[str, SnapshotEntry] = {}
        to_hash: list[tuple[str, Path, os.stat_result]] = []
        for path in sorted(self.root.rglob("*")):
            rel = clean_rel(path.relative_to(self.root).as_posix())
            if is_hidden_rel(rel) or is_excluded(rel, self.exclude):
                continue
            if path.is_symlink():
                continue
            if path.is_dir():
                out[rel] = SnapshotEntry(path=rel, type="folder", mtime=path.stat().st_mtime)
            elif path.is_file():
                stat = path.stat()
                previous = baseline.get(rel)
                if (
                    previous is not None
                    and previous.type == "file"
                    and previous.local_sha256 is not None
                    and previous.local_size == stat.st_size
                    and previous.local_mtime_ns == stat.st_mtime_ns
                ):
                    digest = previous.local_sha256
                    out[rel] = SnapshotEntry(
                        path=rel,
                        type="file",
                        sha256=digest,
                        size=stat.st_size,
                        mtime=stat.st_mtime,
                        local_sha256=digest,
                        local_size=stat.st_size,
                        local_mtime_ns=stat.st_mtime_ns,
                    )
                else:
                    to_hash.append((rel, path, stat))

        if to_hash:
            with ThreadPoolExecutor(max_workers=_HASH_WORKERS) as executor:
                for rel, entry in executor.map(_hashed_entry, to_hash):
                    out[rel] = entry
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
