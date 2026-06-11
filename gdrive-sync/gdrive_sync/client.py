from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from pathlib import Path

import lib.env  # noqa: F401 - load repo .env regardless of cwd

from .drive import DriveTree
from .local import LocalTree
from .lock import PairingLock
from .logging_config import configure_logging
from .planner import plan_pull, plan_push, plan_sync
from .state import SyncState, default_state_dir
from .types import ConflictPolicy, OperationResult, PlannedAction, SnapshotEntry, SyncOperationFailed
from .util import clean_rel

logger = logging.getLogger(__name__)


class GDriveSync:
    def __init__(
        self,
        *,
        local_root: str | None = None,
        gdrive_root: str | None = None,
        credentials_path: str | None = None,
        token_path: str | None = None,
        exclude: list[str] | None = None,
        lock_timeout: float = 1800,
        state_dir: str | None = None,
        log_dir: str | None = None,
        verbose: bool = False,
    ):
        configure_logging(log_dir, verbose=verbose)
        self.local_root = local_root or os.environ.get("STORAGE_MIRROR_PATH")
        self.gdrive_root = gdrive_root or os.environ.get("STORAGE_PATH") or "root"
        self.credentials_path = (
            credentials_path
            or os.environ.get("GDRIVE_CREDENTIALS")
            or os.path.expanduser("~/.openclaw/gdrive-ops-credentials.json")
        )
        self.token_path = (
            token_path
            or os.environ.get("GDRIVE_TOKEN")
            or os.path.expanduser("~/.openclaw/gdrive-ops-token.json")
        )
        if not self.local_root:
            raise ValueError("local_root is required or STORAGE_MIRROR_PATH must be set")
        if not os.path.isabs(self.local_root):
            raise ValueError(f"local_root must be absolute: {self.local_root}")
        self.exclude = exclude or []
        self.lock_timeout = lock_timeout
        self.local = LocalTree(self.local_root, exclude=self.exclude)
        self.drive = DriveTree(
            root_folder_id=self.gdrive_root,
            credentials_path=self.credentials_path,
            token_path=self.token_path,
            exclude=self.exclude,
        )
        self.identity = self._pairing_identity()
        root_state_dir = Path(state_dir).expanduser() if state_dir else default_state_dir()
        self.pairing_dir = root_state_dir / self.identity
        self.state = SyncState(self.pairing_dir / "state.sqlite3")
        self.lock_path = self.pairing_dir / "pairing.lock"

    def push(self, dry_run: bool = False) -> OperationResult:
        return self._run("push", dry_run=dry_run)

    def pull(self, dry_run: bool = False) -> OperationResult:
        return self._run("pull", dry_run=dry_run)

    def sync(self, *, conflict_policy: ConflictPolicy = "local-wins", dry_run: bool = False) -> OperationResult:
        return self._run("sync", conflict_policy=conflict_policy, dry_run=dry_run)

    def _pairing_identity(self) -> str:
        raw = f"{Path(self.local_root).resolve()}|{self.gdrive_root}|{Path(self.token_path).expanduser()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _run(
        self,
        operation: str,
        *,
        conflict_policy: ConflictPolicy = "local-wins",
        dry_run: bool,
    ) -> OperationResult:
        if operation == "pull":
            return self._run_pull_streaming(dry_run=dry_run)
        start = time.monotonic()
        result = OperationResult(operation=operation, dry_run=dry_run)
        with PairingLock(self.lock_path, timeout=self.lock_timeout, operation=operation):
            baseline = self.state.load_baseline()
            logger.info("%s local scan started", operation)
            local_snapshot = self.local.scan()
            logger.info("%s local scan finished: entries=%s", operation, len(local_snapshot))
            cloud_snapshot, warnings, failures = self.drive.scan()
            result.warnings.extend(warnings)
            result.failures.extend(failures)
            if operation == "push":
                actions = plan_push(local_snapshot, cloud_snapshot)
            elif operation == "pull":
                actions = plan_pull(local_snapshot, cloud_snapshot)
            else:
                actions = plan_sync(
                    baseline,
                    local_snapshot,
                    cloud_snapshot,
                    conflict_policy=conflict_policy,
                )
            logger.info("%s planned %s actions", operation, len(actions))
            for action in actions:
                self._apply(action, result, dry_run=dry_run)
            if not dry_run and not result.failures:
                logger.info("%s committing baseline", operation)
                if operation == "pull":
                    merged = dict(cloud_snapshot)
                elif operation == "push":
                    merged = dict(local_snapshot)
                else:
                    local_snapshot = self.local.scan()
                    cloud_snapshot, warnings, failures = self.drive.scan()
                    result.warnings.extend(warnings)
                    result.failures.extend(failures)
                    merged = self._merged_baseline(local_snapshot, cloud_snapshot)
                if not result.failures:
                    self.state.save_baseline(merged)
                    token = self.drive.start_page_token()
                    if token:
                        self.state.set_metadata("drive_start_page_token", token)
            result.elapsed_seconds = time.monotonic() - start
        if result.failures:
            raise SyncOperationFailed("sync completed with failures", partial_result=result)
        return result

    def _run_pull_streaming(self, *, dry_run: bool) -> OperationResult:
        start = time.monotonic()
        result = OperationResult(operation="pull", dry_run=dry_run)
        with PairingLock(self.lock_path, timeout=self.lock_timeout, operation="pull"):
            active_operation_id = self.state.get_metadata("active_operation_id")
            if active_operation_id and active_operation_id.startswith("pull-"):
                operation_id = active_operation_id
                logger.info("pull resuming checkpoint %s", operation_id)
            else:
                operation_id = f"pull-{uuid.uuid4().hex}"
                logger.info("pull starting checkpoint %s", operation_id)
            if not dry_run:
                self.state.set_metadata("active_operation_id", operation_id)
            logger.info("pull local scan started")
            local_snapshot = self.local.scan()
            logger.info("pull local scan finished: entries=%s", len(local_snapshot))
            checkpoint = self.state.load_checkpoint(operation_id) if not dry_run else {}
            if checkpoint:
                logger.info("pull loaded checkpoint entries=%s", len(checkpoint))
            cloud_snapshot: dict[str, SnapshotEntry] = {}
            for entry, content, warning, failure in self.drive.iter_entries_with_content(
                checkpoint=checkpoint,
                local_snapshot=local_snapshot,
            ):
                if warning:
                    result.warnings.append(warning)
                    logger.warning(warning)
                    continue
                if failure:
                    result.failures.append(failure)
                    logger.error(failure)
                    continue
                if entry is None:
                    continue
                cloud_snapshot[entry.path] = entry
                local_entry = local_snapshot.get(entry.path)
                if entry.type == "folder":
                    if local_entry is None:
                        logger.info("pull mkdir %s", entry.path)
                        if dry_run:
                            result.skipped_entries.append(f"dry-run:mkdir:{entry.path}")
                        else:
                            self.local.mkdir(entry.path)
                        result.created_folders.append(entry.path)
                    if not dry_run:
                        self.state.save_checkpoint_entry(operation_id, entry)
                    continue
                if local_entry is not None and local_entry.type == "file" and local_entry.sha256 == entry.sha256:
                    result.skipped_entries.append(entry.path)
                    if not dry_run:
                        self.state.save_checkpoint_entry(operation_id, entry)
                    continue
                if content is None:
                    result.failures.append(f"{entry.path}: Drive file yielded no content")
                    continue
                logger.info("pull write %s (%s bytes)", entry.path, len(content))
                if dry_run:
                    result.skipped_entries.append(f"dry-run:write:{entry.path}")
                else:
                    self.local.write_bytes_atomic(entry.path, content)
                    self.state.save_checkpoint_entry(operation_id, entry)
                result.bytes_transferred += len(content)
                if local_entry is None:
                    result.created_files.append(entry.path)
                else:
                    result.updated_files.append(entry.path)
            for path in sorted(set(local_snapshot) - set(cloud_snapshot), reverse=True):
                logger.info("pull delete local %s", path)
                if dry_run:
                    result.skipped_entries.append(f"dry-run:delete:{path}")
                else:
                    self.local.remove(path)
                    self.local.prune_empty_parents(path)
                result.deleted_entries.append(path)
            if not dry_run and not result.failures:
                logger.info("pull committing baseline")
                self.state.promote_checkpoint_to_baseline(operation_id)
                token = self.drive.start_page_token()
                if token:
                    self.state.set_metadata("drive_start_page_token", token)
                self.state.set_metadata("active_operation_id", "")
            result.elapsed_seconds = time.monotonic() - start
        if result.failures:
            raise SyncOperationFailed("pull completed with failures", partial_result=result)
        return result

    def _merged_baseline(
        self,
        local_snapshot: dict[str, SnapshotEntry],
        cloud_snapshot: dict[str, SnapshotEntry],
    ) -> dict[str, SnapshotEntry]:
        merged = dict(local_snapshot)
        for path, entry in cloud_snapshot.items():
            merged.setdefault(path, entry)
        return merged

    def _apply(self, action: PlannedAction, result: OperationResult, *, dry_run: bool) -> None:
        target_path = action.conflict_path or action.path
        logger.info("%s %s", action.action, target_path)
        if action.action == "conflict":
            result.conflicts.append(action.path)
            return
        if dry_run:
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
