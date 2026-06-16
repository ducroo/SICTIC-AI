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
class IncrementalDecision:
    path: str
    source: Side
    conflict: bool = False


@dataclass
class CloudMutations:
    drive_ids: set[str] = field(default_factory=set)
    paths: set[str] = field(default_factory=set)

    def add(self, path: str | None = None, drive_id: str | None = None) -> None:
        if path:
            self.paths.add(path)
        if drive_id:
            self.drive_ids.add(drive_id)


@dataclass
class TransferProgress:
    total: int = 0
    completed: int = 0

    def log(self, verb: str, path: str, size: int) -> None:
        import logging

        self.completed += 1
        logger = logging.getLogger(__name__)
        if self.total:
            logger.info(
                "%s %s/%s %s (%s bytes)",
                verb,
                self.completed,
                self.total,
                path,
                size,
            )
            return
        logger.info("%s %s (%s bytes)", verb, path, size)


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
    self_generated_drive_changes: int = 0
    external_drive_changes_after_sync: int = 0
    quiet_wait_rounds: int = 0

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
