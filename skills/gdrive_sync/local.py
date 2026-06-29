from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .types import SnapshotEntry
from .util import clean_rel, is_excluded, is_hidden_rel, sha256_file


logger = logging.getLogger(__name__)
_HASH_WORKERS = min(8, os.cpu_count() or 4)
_HASH_PROGRESS_INTERVAL = 500


def _hashed_entry(item: tuple[str, Path, os.stat_result]) -> tuple[str, SnapshotEntry]:
    rel, path, stat = item
    digest = sha256_file(path)
    return rel, SnapshotEntry(
        path=rel,
        type="file",
        sha256=digest,
        size=stat.st_size,
        mtime=stat.st_mtime,
    )


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
        to_hash: list[tuple[str, Path, os.stat_result]] = []
        for current_root, dirnames, filenames in os.walk(self.root, topdown=True):
            current = Path(current_root)

            kept_dirnames = []
            for dirname in sorted(dirnames):
                path = current / dirname
                rel = clean_rel(path.relative_to(self.root).as_posix())
                if path.is_symlink() or is_hidden_rel(rel) or is_excluded(rel, self.exclude):
                    continue
                kept_dirnames.append(dirname)
                out[rel] = SnapshotEntry(path=rel, type="folder", mtime=path.stat().st_mtime)
            dirnames[:] = kept_dirnames

            for filename in sorted(filenames):
                path = current / filename
                rel = clean_rel(path.relative_to(self.root).as_posix())
                if path.is_symlink() or is_hidden_rel(rel) or is_excluded(rel, self.exclude):
                    continue
                if path.is_file():
                    stat = path.stat()
                    to_hash.append((rel, path, stat))

        if to_hash:
            started = time.monotonic()
            total = len(to_hash)
            logger.info(
                "Hashing %s local files with %s workers.",
                total,
                _HASH_WORKERS,
            )
            with ThreadPoolExecutor(max_workers=_HASH_WORKERS) as executor:
                for index, (rel, entry) in enumerate(
                    executor.map(_hashed_entry, to_hash),
                    start=1,
                ):
                    out[rel] = entry
                    if index % _HASH_PROGRESS_INTERVAL == 0 or index == total:
                        logger.info("Hashed local files %s/%s.", index, total)
            logger.info(
                "Hashed %s local files in %.2fs.",
                total,
                time.monotonic() - started,
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
