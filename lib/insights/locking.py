from __future__ import annotations

import fcntl
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

_manifest_locks: dict[str, threading.Lock] = {}
_manifest_locks_guard = threading.Lock()


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def write_if_changed(storage, path: str, content: str) -> None:
    if storage.exists(path) and storage.read_text(path) == content:
        return
    atomic_write(Path(storage.local_path(path)), content)


def _thread_lock(path: str) -> threading.Lock:
    with _manifest_locks_guard:
        return _manifest_locks.setdefault(path, threading.Lock())


@contextmanager
def manifest_write_lock(manifest_path: Path):
    lock_path = manifest_path.with_name(f"{manifest_path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _thread_lock(str(lock_path)):
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
