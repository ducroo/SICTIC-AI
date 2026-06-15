from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .state import SyncState


@dataclass(frozen=True)
class SyncContext:
    local: object
    drive: object
    executor: object
    state: SyncState
    lock_path: Path | str
    lock_timeout: float
    lock_factory: Callable
