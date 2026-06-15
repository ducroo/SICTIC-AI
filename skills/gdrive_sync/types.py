from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ConflictPolicy = Literal["local-wins", "cloud-wins"]
Side = Literal["local", "cloud"]
EntryType = Literal["file", "folder"]


@dataclass(frozen=True)
class SnapshotEntry:
    path: str
    type: EntryType
    sha256: str | None = None
    size: int | None = None
    mtime: float | None = None
    drive_id: str | None = None
    mime_type: str | None = None


@dataclass(frozen=True)
class PlannedAction:
    action: str
    path: str
    source: Side | None = None
    target: Side | None = None
    conflict_path: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class IncrementalDecision:
    path: str
    source: Side
    conflict: bool = False


@dataclass
class OperationResult:
    operation: str
    dry_run: bool = False
    created_files: list[str] = field(default_factory=list)
    created_folders: list[str] = field(default_factory=list)
    updated_files: list[str] = field(default_factory=list)
    deleted_entries: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    skipped_entries: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    bytes_transferred: int = 0
    elapsed_seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.failures


class GDriveSyncError(Exception):
    def __init__(self, message: str, *, partial_result: OperationResult | None = None):
        super().__init__(message)
        self.partial_result = partial_result


class SyncLockTimeout(GDriveSyncError):
    pass


class SyncOperationFailed(GDriveSyncError):
    pass
