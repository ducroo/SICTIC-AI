from __future__ import annotations

import logging
from pathlib import Path

from .executor import TransferProgress
from .types import ConflictPolicy, OperationResult, SnapshotEntry
from .util import clean_rel, conflict_name

logger = logging.getLogger(__name__)


class IncrementalActions:
    def __init__(self, context):
        self.context = context
        self.cloud_mutation_ids: set[str] = set()

    @property
    def local(self):
        return self.context.local

    @property
    def drive(self):
        return self.context.drive

    @property
    def state(self):
        return self.context.state

    def apply_local_change_to_cloud(
        self,
        path: str,
        local_entry: SnapshotEntry | None,
        baseline_entry: SnapshotEntry | None,
        result: OperationResult,
        progress: TransferProgress,
        *,
        dry_run: bool,
    ) -> None:
        if local_entry is None:
            logger.info("sync delete cloud %s", path)
            if dry_run:
                result.skipped_entries.append(f"dry-run:delete-cloud:{path}")
            else:
                self.drive.remove(path)
                if baseline_entry and baseline_entry.drive_id:
                    self.cloud_mutation_ids.add(baseline_entry.drive_id)
                self.state.delete_baseline_path(
                    path,
                    include_descendants=(
                        baseline_entry is not None and baseline_entry.type == "folder"
                    ),
                )
            result.deleted_entries.append(path)
            return

        if local_entry.type == "folder":
            logger.info("sync mkdir cloud %s", path)
            if dry_run:
                result.skipped_entries.append(f"dry-run:mkdir-cloud:{path}")
            else:
                self.drive.mkdir(path)
                entry = self.drive.entry_after_mkdir(path)
                self.state.upsert_baseline_entry(entry)
                if entry.drive_id:
                    self.cloud_mutation_ids.add(entry.drive_id)
            result.created_folders.append(path)
            return

        content = self.local.read_bytes(path)
        progress.log("upload", path, len(content))
        if dry_run:
            result.skipped_entries.append(f"dry-run:upload:{path}")
        else:
            try:
                self.drive.write_bytes(path, content)
                entry = self.drive.entry_after_write(path, content)
                self.state.upsert_baseline_entry(entry)
                if entry.drive_id:
                    self.cloud_mutation_ids.add(entry.drive_id)
            except Exception as error:
                message = f"{path}: {error}"
                logger.error(message)
                result.failures.append(message)
                return
        result.bytes_transferred += len(content)
        if baseline_entry is None:
            result.created_files.append(path)
        else:
            result.updated_files.append(path)

    def apply_cloud_change_to_local(
        self,
        path: str,
        cloud_entry: SnapshotEntry | None,
        content: bytes | None,
        local_snapshot: dict[str, SnapshotEntry],
        result: OperationResult,
        progress: TransferProgress,
        *,
        dry_run: bool,
    ) -> None:
        if cloud_entry is None:
            self.delete_local(path, result, dry_run=dry_run)
            local_snapshot.pop(path, None)
            return
        if cloud_entry.type == "folder":
            self.apply_pull_folder(
                cloud_entry,
                local_snapshot,
                result,
                dry_run=dry_run,
            )
            return
        self.apply_pull_file(
            cloud_entry,
            content,
            local_snapshot,
            result,
            progress=progress,
            dry_run=dry_run,
        )

    def apply_conflict(
        self,
        path: str,
        baseline_entry: SnapshotEntry | None,
        local_entry: SnapshotEntry | None,
        cloud_entry: SnapshotEntry | None,
        cloud_content: bytes | None,
        local_snapshot: dict[str, SnapshotEntry],
        conflict_policy: ConflictPolicy,
        result: OperationResult,
        progress: TransferProgress,
        existing_paths: set[str],
        *,
        dry_run: bool,
    ) -> None:
        logger.info("sync conflict %s policy=%s", path, conflict_policy)
        result.conflicts.append(path)
        losing_entry = (
            cloud_entry if conflict_policy == "local-wins" else local_entry
        )
        if losing_entry is not None and losing_entry.type == "file":
            tag = (
                "conflict-cloud"
                if conflict_policy == "local-wins"
                else "conflict-local"
            )
            conflict_path = conflict_name(path, tag, existing_paths)
            try:
                losing_content = (
                    cloud_content
                    if conflict_policy == "local-wins"
                    else self.local.read_bytes(path)
                )
                if losing_content is None:
                    raise ValueError("conflicting cloud file has no content")
                self._preserve_conflict(
                    path,
                    conflict_path,
                    losing_content,
                    result,
                    progress,
                    dry_run=dry_run,
                )
            except Exception as error:
                message = f"{path}: failed to preserve conflict: {error}"
                logger.error(message)
                result.failures.append(message)
                return

        if conflict_policy == "local-wins":
            self.apply_local_change_to_cloud(
                path,
                local_entry,
                baseline_entry,
                result,
                progress,
                dry_run=dry_run,
            )
        else:
            self.apply_cloud_change_to_local(
                path,
                cloud_entry,
                cloud_content,
                local_snapshot,
                result,
                progress,
                dry_run=dry_run,
            )

    def _preserve_conflict(
        self,
        path: str,
        conflict_path: str,
        content: bytes,
        result: OperationResult,
        progress: TransferProgress,
        *,
        dry_run: bool,
    ) -> None:
        logger.info("sync preserve conflict %s as %s", path, conflict_path)
        progress.log("download", conflict_path, len(content))
        progress.log("upload", conflict_path, len(content))
        if dry_run:
            result.skipped_entries.extend(
                [
                    f"dry-run:conflict-local:{conflict_path}",
                    f"dry-run:conflict-cloud:{conflict_path}",
                ]
            )
            return

        self.local.write_bytes_atomic(conflict_path, content)
        parent = str(Path(conflict_path).parent).replace("\\", "/")
        if parent != ".":
            self.drive.mkdir(clean_rel(parent))
        self.drive.write_bytes(conflict_path, content)
        entry = self.drive.entry_after_write(conflict_path, content)
        self.state.upsert_baseline_entry(entry)
        if entry.drive_id:
            self.cloud_mutation_ids.add(entry.drive_id)
        result.bytes_transferred += len(content) * 2
        result.created_files.append(conflict_path)

    def apply_incremental_entry(
        self,
        entry: SnapshotEntry | None,
        content: bytes | None,
        warning: str | None,
        failure: str | None,
        local_snapshot: dict[str, SnapshotEntry],
        result: OperationResult,
        *,
        progress: TransferProgress | None = None,
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
            self.apply_pull_folder(entry, local_snapshot, result, dry_run=dry_run)
        else:
            self.apply_pull_file(
                entry,
                content,
                local_snapshot,
                result,
                progress=progress,
                dry_run=dry_run,
            )
        if not dry_run:
            self.state.upsert_baseline_entry(entry)

    def apply_pull_folder(
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

    def apply_pull_file(
        self,
        entry: SnapshotEntry,
        content: bytes | None,
        local_snapshot: dict[str, SnapshotEntry],
        result: OperationResult,
        *,
        progress: TransferProgress | None = None,
        dry_run: bool,
    ) -> None:
        local_entry = local_snapshot.get(entry.path)
        if (
            local_entry is not None
            and local_entry.type == "file"
            and local_entry.sha256 == entry.sha256
        ):
            result.skipped_entries.append(entry.path)
            return
        if content is None:
            result.failures.append(f"{entry.path}: Drive file yielded no content")
            return
        if progress is None:
            logger.info("download %s (%s bytes)", entry.path, len(content))
        else:
            progress.log("download", entry.path, len(content))
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

    def delete_local(
        self,
        path: str,
        result: OperationResult,
        *,
        dry_run: bool,
    ) -> None:
        logger.info("pull delete local %s", path)
        if dry_run:
            result.skipped_entries.append(f"dry-run:delete:{path}")
        else:
            self.local.remove(path)
            self.local.prune_empty_parents(path)
        result.deleted_entries.append(path)
