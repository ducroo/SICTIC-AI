from __future__ import annotations

import fcntl
import json
import os
import socket
import time
from pathlib import Path

from .types import SyncLockTimeout


class PairingLock:
    def __init__(self, path: Path, *, timeout: float, operation: str):
        self.path = path
        self.timeout = timeout
        self.operation = operation
        self._handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+")
        start = time.monotonic()
        while True:
            try:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._handle.seek(0)
                self._handle.truncate()
                self._handle.write(
                    json.dumps(
                        {
                            "pid": os.getpid(),
                            "hostname": socket.gethostname(),
                            "operation": self.operation,
                            "start_time": time.time(),
                        },
                        sort_keys=True,
                    )
                )
                self._handle.flush()
                return self
            except BlockingIOError:
                if time.monotonic() - start >= self.timeout:
                    raise SyncLockTimeout(f"timed out waiting for sync lock: {self.path}")
                time.sleep(min(5.0, max(0.1, self.timeout / 60)))

    def __exit__(self, exc_type, exc, tb):
        if self._handle is not None:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            self._handle.close()
            self._handle = None
        return False
