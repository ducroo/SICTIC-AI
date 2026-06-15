from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .types import OperationResult, PlannedAction
from .util import clean_rel

logger = logging.getLogger(__name__)


@dataclass
class TransferProgress:
    total: int
    current: int = 0

    def log(self, direction: str, path: str, size: int) -> None:
        self.current += 1
        logger.info(
            "%s %s/%s %s (%s bytes)",
            direction,
            self.current,
            self.total,
            path,
            size,
        )


class SyncExecutor:
    def __init__(self, *, local, drive):
        self.local = local
        self.drive = drive

    def apply(
        self,
        action: PlannedAction,
        result: OperationResult,
        *,
        dry_run: bool,
        progress: TransferProgress,
    ) -> None:
        target_path = action.conflict_path or action.path
        if action.action == "conflict":
            logger.info("conflict %s policy=%s", action.path, action.message)
            result.conflicts.append(action.path)
            return
        if action.action not in {"copy", "copy_as"}:
            logger.info("%s %s", action.action, target_path)
        if dry_run:
            logger.info("dry-run %s %s", action.action, target_path)
            result.skipped_entries.append(f"dry-run:{action.action}:{target_path}")
            return
        try:
            if action.action == "mkdir":
                if action.target == "local":
                    self.local.mkdir(action.path)
                elif action.target == "cloud":
                    self.drive.mkdir(action.path)
                result.created_folders.append(action.path)
            elif action.action == "delete":
                if action.target == "local":
                    self.local.remove(action.path)
                    self.local.prune_empty_parents(action.path)
                elif action.target == "cloud":
                    self.drive.remove(action.path)
                result.deleted_entries.append(action.path)
            elif action.action in {"copy", "copy_as"}:
                content = self._read_source(action)
                direction = "download" if action.target == "local" else "upload"
                progress.log(direction, target_path, len(content))
                if action.target == "local":
                    self.local.write_bytes_atomic(target_path, content)
                elif action.target == "cloud":
                    parent = str(Path(target_path).parent).replace("\\", "/")
                    if parent != ".":
                        self.drive.mkdir(clean_rel(parent))
                    self.drive.write_bytes(target_path, content)
                result.bytes_transferred += len(content)
                if action.action == "copy_as":
                    result.conflicts.append(action.path)
                    result.created_files.append(target_path)
                else:
                    result.updated_files.append(target_path)
            else:
                result.warnings.append(f"{action.path}: unknown action {action.action}")
        except Exception as exc:
            result.failures.append(f"{target_path}: {exc}")

    def _read_source(self, action: PlannedAction) -> bytes:
        if action.source == "local":
            return self.local.read_bytes(action.path)
        if action.source == "cloud":
            return self.drive.read_bytes(action.path)
        raise ValueError(f"copy action has no source: {action}")
