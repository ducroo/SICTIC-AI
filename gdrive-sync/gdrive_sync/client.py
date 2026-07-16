from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from pathlib import Path

from googleapiclient.errors import HttpError
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
        cloud_provider = os.environ.get("CLOUD_PROVIDER", "").strip().lower()
        if cloud_provider != "google":
            raise ValueError("gdrive_sync requires CLOUD_PROVIDER=google")

        self.local_root = local_root or os.environ.get("LOCAL_STORAGE_PATH")
        configured_gdrive_root = (
            gdrive_root
            if gdrive_root is not None
            else os.environ.get("CLOUD_STORAGE_PATH")
        )
        self.gdrive_root = (configured_gdrive_root or "").strip()
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
            raise ValueError("local_root is required or LOCAL_STORAGE_PATH must be set")
        if not self.gdrive_root:
            raise ValueError(
                "gdrive_root is required or CLOUD_STORAGE_PATH must be set "
                "explicitly. Use CLOUD_STORAGE_PATH=root only if syncing the "
                "Google Drive root is intentional."
            )
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
            active_operation_id = self.state.get_metadata("active_operation_id")
            baseline = self.state.load_baseline()
            token = self.state.get_metadata("drive_start_page_token")
            if token and baseline and not active_operation_id:
                try:
                    return self._run_pull_incremental(token=token, baseline=baseline, dry_run=dry_run)
                except HttpError as exc:
                    if getattr(exc.resp, "status", None) == 410:
                        logger.warning("Drive changes token expired; falling back to full pull")
                    else:
                        raise
            return self._run_pull_streaming(dry_run=dry_run)
        if operation == "sync":
            active_operation_id = self.state.get_metadata("active_operation_id")
            baseline = self.state.load_baseline()
            token = self.state.get_metadata("drive_start_page_token")
            if token and baseline and not active_operation_id:
                try:
                    return self._run_sync_incremental(
                        token=token,
                        baseline=baseline,
                        conflict_policy=conflict_policy,
                        dry_run=dry_run,
                    )
                except HttpError as exc:
                    if getattr(exc.resp, "status", None) == 410:
                        result = OperationResult(operation="sync", dry_run=dry_run)
                        result.failures.append(
                            "Drive changes token expired; run `gdrive-sync pull` to refresh the baseline before incremental sync."
                        )
                        raise SyncOperationFailed("incremental sync cannot continue", partial_result=result) from exc
                    raise
            result = OperationResult(operation="sync", dry_run=dry_run)
            if active_operation_id:
                result.failures.append(f"cannot sync while operation checkpoint is active: {active_operation_id}")
            elif not baseline:
                result.failures.append("cannot incremental sync without a successful baseline; run `gdrive-sync pull` first")
            elif not token:
                result.failures.append("cannot incremental sync without a Drive changes token; run `gdrive-sync pull` first")
            else:
                result.failures.append("cannot incremental sync; unknown prerequisite failure")
            raise SyncOperationFailed("incremental sync prerequisites missing", partial_result=result)
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

    def _run_pull_incremental(
        self,
        *,
        token: str,
        baseline: dict[str, SnapshotEntry],
        dry_run: bool,
    ) -> OperationResult:
        start = time.monotonic()
        result = OperationResult(operation="pull", dry_run=dry_run)
        with PairingLock(self.lock_path, timeout=self.lock_timeout, operation="pull"):
            logger.info("pull incremental changes.list started")
            local_snapshot = self.local.scan()
            baseline_by_drive_id = {
                entry.drive_id: entry for entry in baseline.values() if entry.drive_id
            }
            changes, new_token = self.drive.list_changes(token)
            logger.info("pull incremental applying %s Drive changes", len(changes))
            for change in changes:
                file_id = change.get("fileId")
                old_entry = baseline_by_drive_id.get(file_id)
                removed = change.get("removed") or (change.get("file") or {}).get("trashed")
                if removed:
                    if old_entry:
                        self._delete_local_from_pull(old_entry.path, result, dry_run=dry_run)
                        if not dry_run:
                            self.state.delete_baseline_path(
                                old_entry.path,
                                include_descendants=old_entry.type == "folder",
                            )
                    continue

                entry, content, warning, failure = self.drive.entry_for_change(change)
                if warning:
                    result.warnings.append(warning)
                    logger.warning(warning)
                    continue
                if failure:
                    result.failures.append(failure)
                    logger.error(failure)
                    continue
                if entry is None:
                    if old_entry:
                        self._delete_local_from_pull(old_entry.path, result, dry_run=dry_run)
                        if not dry_run:
                            self.state.delete_baseline_path(
                                old_entry.path,
                                include_descendants=old_entry.type == "folder",
                            )
                    continue

                if old_entry and old_entry.path != entry.path:
                    self._delete_local_from_pull(old_entry.path, result, dry_run=dry_run)
                    if not dry_run:
                        self.state.delete_baseline_path(
                            old_entry.path,
                            include_descendants=old_entry.type == "folder",
                        )

                if entry.type == "folder":
                    self._apply_pull_folder(entry, local_snapshot, result, dry_run=dry_run)
                    if not dry_run:
                        self.state.upsert_baseline_entry(entry)
                    should_walk_subtree = old_entry is None or old_entry.path != entry.path
                    if not should_walk_subtree:
                        continue
                    for child_entry, child_content, child_warning, child_failure in self.drive.iter_subtree_with_content(
                        root_id=entry.drive_id or "",
                        root_path=entry.path,
                        local_snapshot=local_snapshot,
                    ):
                        self._apply_incremental_entry(
                            child_entry,
                            child_content,
                            child_warning,
                            child_failure,
                            local_snapshot,
                            result,
                            dry_run=dry_run,
                        )
                    continue

                self._apply_pull_file(entry, content, local_snapshot, result, dry_run=dry_run)
                if not dry_run and not result.failures:
                    self.state.upsert_baseline_entry(entry)

            if not dry_run and not result.failures:
                self.state.set_metadata("drive_start_page_token", new_token)
            result.elapsed_seconds = time.monotonic() - start
        if result.failures:
            raise SyncOperationFailed("incremental pull completed with failures", partial_result=result)
        return result

    def _run_sync_incremental(
        self,
        *,
        token: str,
        baseline: dict[str, SnapshotEntry],
        conflict_policy: ConflictPolicy,
        dry_run: bool,
    ) -> OperationResult:
        start = time.monotonic()
        result = OperationResult(operation="sync", dry_run=dry_run)
        with PairingLock(self.lock_path, timeout=self.lock_timeout, operation="sync"):
            logger.info("sync incremental local scan started")
            local_snapshot = self.local.scan()
            logger.info("sync incremental local scan finished: entries=%s", len(local_snapshot))
            local_changed = {
                path
                for path in set(baseline) | set(local_snapshot)
                if self._entry_changed(local_snapshot.get(path), baseline.get(path))
            }

            logger.info("sync incremental changes.list started")
            baseline_by_drive_id = {
                entry.drive_id: entry for entry in baseline.values() if entry.drive_id
            }
            changes, _ = self.drive.list_changes(token)
            cloud_entries: dict[str, SnapshotEntry] = {}
            cloud_content: dict[str, bytes] = {}
            cloud_deleted: set[str] = set()
            baseline_updates: dict[str, SnapshotEntry] = {}

            for change in changes:
                file_id = change.get("fileId")
                old_entry = baseline_by_drive_id.get(file_id)
                removed = change.get("removed") or (change.get("file") or {}).get("trashed")
                if removed:
                    if old_entry:
                        cloud_deleted.add(old_entry.path)
                    continue

                entry, content, warning, failure = self.drive.entry_for_change(change)
                if warning:
                    result.warnings.append(warning)
                    logger.warning(warning)
                    continue
                if failure:
                    result.failures.append(failure)
                    logger.error(failure)
                    continue
                if entry is None:
                    if old_entry:
                        cloud_deleted.add(old_entry.path)
                    continue
                if old_entry and old_entry.path != entry.path:
                    cloud_deleted.add(old_entry.path)

                cloud_entries[entry.path] = entry
                baseline_updates[entry.path] = entry
                if content is not None:
                    cloud_content[entry.path] = content

                if entry.type == "folder":
                    should_walk_subtree = old_entry is None or old_entry.path != entry.path
                    if should_walk_subtree:
                        for child_entry, child_content, child_warning, child_failure in self.drive.iter_subtree_with_content(
                            root_id=entry.drive_id or "",
                            root_path=entry.path,
                            local_snapshot=local_snapshot,
                        ):
                            if child_warning:
                                result.warnings.append(child_warning)
                                logger.warning(child_warning)
                                continue
                            if child_failure:
                                result.failures.append(child_failure)
                                logger.error(child_failure)
                                continue
                            if child_entry is None:
                                continue
                            cloud_entries[child_entry.path] = child_entry
                            baseline_updates[child_entry.path] = child_entry
                            if child_content is not None:
                                cloud_content[child_entry.path] = child_content

            affected_paths = sorted(local_changed | set(cloud_entries) | cloud_deleted)
            logger.info(
                "sync incremental applying paths=%s local_changes=%s cloud_changes=%s cloud_deletes=%s",
                len(affected_paths),
                len(local_changed),
                len(cloud_entries),
                len(cloud_deleted),
            )
            for path in affected_paths:
                base = baseline.get(path)
                local_entry = local_snapshot.get(path)
                has_local_change = path in local_changed
                has_cloud_change = path in cloud_entries or path in cloud_deleted

                if has_local_change and has_cloud_change:
                    self._apply_incremental_conflict(
                        path,
                        base,
                        local_entry,
                        cloud_entries.get(path),
                        cloud_content.get(path),
                        conflict_policy,
                        result,
                        dry_run=dry_run,
                    )
                elif has_local_change:
                    if conflict_policy != "cloud-wins":
                        self._apply_local_change_to_cloud(path, local_entry, base, result, dry_run=dry_run)
                elif has_cloud_change:
                    if path in cloud_deleted and conflict_policy == "cloud-wins":
                        logger.info("sync skip cloud delete %s (cloud-wins is non-destructive)", path)
                        continue
                    self._apply_cloud_change_to_local(
                        path,
                        cloud_entries.get(path),
                        cloud_content.get(path),
                        result,
                        dry_run=dry_run,
                    )

            if not dry_run and not result.failures:
                if conflict_policy != "cloud-wins":
                    for path in cloud_deleted:
                        self.state.delete_baseline_path(path, include_descendants=(baseline.get(path) or SnapshotEntry(path, "file")).type == "folder")
                for path, entry in baseline_updates.items():
                    self.state.upsert_baseline_entry(entry)
                token_after_writes = self.drive.start_page_token()
                if token_after_writes:
                    self.state.set_metadata("drive_start_page_token", token_after_writes)
            result.elapsed_seconds = time.monotonic() - start
        if result.failures:
            raise SyncOperationFailed("incremental sync completed with failures", partial_result=result)
        return result

    @staticmethod
    def _entry_changed(current: SnapshotEntry | None, baseline: SnapshotEntry | None) -> bool:
        if current is None:
            return baseline is not None
        if baseline is None:
            return True
        if current.type != baseline.type:
            return True
        if current.type == "folder":
            return False
        return current.sha256 != baseline.sha256

    def _apply_local_change_to_cloud(
        self,
        path: str,
        local_entry: SnapshotEntry | None,
        baseline_entry: SnapshotEntry | None,
        result: OperationResult,
        *,
        dry_run: bool,
    ) -> None:
        if local_entry is None:
            logger.info("sync delete cloud %s", path)
            if dry_run:
                result.skipped_entries.append(f"dry-run:delete-cloud:{path}")
            else:
                self.drive.remove(path)
                self.state.delete_baseline_path(
                    path,
                    include_descendants=(baseline_entry is not None and baseline_entry.type == "folder"),
                )
            result.deleted_entries.append(path)
            return
        if local_entry.type == "folder":
            logger.info("sync mkdir cloud %s", path)
            if dry_run:
                result.skipped_entries.append(f"dry-run:mkdir-cloud:{path}")
            else:
                self.drive.mkdir(path)
                self.state.upsert_baseline_entry(self.drive.entry_after_mkdir(path))
            result.created_folders.append(path)
            return
        content = self.local.read_bytes(path)
        logger.info("sync upload %s (%s bytes)", path, len(content))
        if dry_run:
            result.skipped_entries.append(f"dry-run:upload:{path}")
        else:
            try:
                self.drive.write_bytes(path, content)
                self.state.upsert_baseline_entry(self.drive.entry_after_write(path, content))
            except Exception as exc:
                result.failures.append(f"{path}: {exc}")
                logger.error("%s: %s", path, exc)
                return
        result.bytes_transferred += len(content)
        if baseline_entry is None:
            result.created_files.append(path)
        else:
            result.updated_files.append(path)

    def _apply_cloud_change_to_local(
        self,
        path: str,
        cloud_entry: SnapshotEntry | None,
        content: bytes | None,
        result: OperationResult,
        *,
        dry_run: bool,
    ) -> None:
        if cloud_entry is None:
            self._delete_local_from_pull(path, result, dry_run=dry_run)
            return
        if cloud_entry.type == "folder":
            self._apply_pull_folder(cloud_entry, self.local.scan(), result, dry_run=dry_run)
            return
        self._apply_pull_file(cloud_entry, content, self.local.scan(), result, dry_run=dry_run)

    def _apply_incremental_conflict(
        self,
        path: str,
        baseline_entry: SnapshotEntry | None,
        local_entry: SnapshotEntry | None,
        cloud_entry: SnapshotEntry | None,
        cloud_content: bytes | None,
        conflict_policy: ConflictPolicy,
        result: OperationResult,
        *,
        dry_run: bool,
    ) -> None:
        logger.info("sync conflict %s policy=%s", path, conflict_policy)
        result.conflicts.append(path)
        if conflict_policy == "local-wins":
            self._apply_local_change_to_cloud(path, local_entry, baseline_entry, result, dry_run=dry_run)
        elif cloud_entry is None:
            logger.info("sync skip cloud delete %s (cloud-wins is non-destructive)", path)
        else:
            self._apply_cloud_change_to_local(path, cloud_entry, cloud_content, result, dry_run=dry_run)

    def _apply_incremental_entry(
        self,
        entry: SnapshotEntry | None,
        content: bytes | None,
        warning: str | None,
        failure: str | None,
        local_snapshot: dict[str, SnapshotEntry],
        result: OperationResult,
        *,
        dry_run: bool,
    ) -> None:
        if warning:
            result.warnings.append(warning)
            logger.warning(warning)
            return
        if failure:
            result.failures.append(failure)
            logger.error(failure)
            return
        if entry is None:
            return
        if entry.type == "folder":
            self._apply_pull_folder(entry, local_snapshot, result, dry_run=dry_run)
        else:
            self._apply_pull_file(entry, content, local_snapshot, result, dry_run=dry_run)
        if not dry_run:
            self.state.upsert_baseline_entry(entry)

    def _apply_pull_folder(
        self,
        entry: SnapshotEntry,
        local_snapshot: dict[str, SnapshotEntry],
        result: OperationResult,
        *,
        dry_run: bool,
    ) -> None:
        local_entry = local_snapshot.get(entry.path)
        if local_entry is not None and local_entry.type == "folder":
            result.skipped_entries.append(entry.path)
            return
        logger.info("pull mkdir %s", entry.path)
        if dry_run:
            result.skipped_entries.append(f"dry-run:mkdir:{entry.path}")
        else:
            self.local.mkdir(entry.path)
            local_snapshot[entry.path] = entry
        result.created_folders.append(entry.path)

    def _apply_pull_file(
        self,
        entry: SnapshotEntry,
        content: bytes | None,
        local_snapshot: dict[str, SnapshotEntry],
        result: OperationResult,
        *,
        dry_run: bool,
    ) -> None:
        local_entry = local_snapshot.get(entry.path)
        if local_entry is not None and local_entry.type == "file" and local_entry.sha256 == entry.sha256:
            result.skipped_entries.append(entry.path)
            return
        if content is None:
            result.failures.append(f"{entry.path}: Drive file yielded no content")
            return
        logger.info("pull write %s (%s bytes)", entry.path, len(content))
        if dry_run:
            result.skipped_entries.append(f"dry-run:write:{entry.path}")
        else:
            self.local.write_bytes_atomic(entry.path, content)
            local_snapshot[entry.path] = entry
        result.bytes_transferred += len(content)
        if local_entry is None:
            result.created_files.append(entry.path)
        else:
            result.updated_files.append(entry.path)

    def _delete_local_from_pull(self, path: str, result: OperationResult, *, dry_run: bool) -> None:
        logger.info("pull delete local %s", path)
        if dry_run:
            result.skipped_entries.append(f"dry-run:delete:{path}")
        else:
            self.local.remove(path)
            self.local.prune_empty_parents(path)
        result.deleted_entries.append(path)

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
