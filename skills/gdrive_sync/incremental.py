from __future__ import annotations

import logging
import time

from .actions import IncrementalActions
from .checkpoint import CheckpointManager
from .executor import TransferProgress
from .planner import (
    changed_paths,
    collapse_local_folder_deletions,
    incremental_transfer_count,
    plan_incremental_changes,
)
from .types import (
    ConflictPolicy,
    OperationResult,
    SnapshotEntry,
    SyncOperationFailed,
)
from .util import sha256_bytes

logger = logging.getLogger(__name__)


def _load_cloud_file(
    context,
    path: str,
    cloud_entries: dict[str, SnapshotEntry],
    cloud_content: dict[str, bytes],
    result: OperationResult,
) -> bool:
    entry = cloud_entries.get(path)
    if entry is None or entry.type != "file" or path in cloud_content:
        return True
    try:
        content = context.drive.read_bytes(path)
    except Exception as error:
        message = f"{path}: failed to read Drive file: {error}"
        logger.error(message)
        result.failures.append(message)
        return False
    cloud_content[path] = content
    cloud_entries[path] = SnapshotEntry(
        path=entry.path,
        type="file",
        sha256=sha256_bytes(content),
        size=len(content),
        mtime=entry.mtime,
        drive_id=entry.drive_id,
        mime_type=entry.mime_type,
    )
    return True


def run_incremental_pull(
    context,
    *,
    token: str,
    baseline: dict[str, SnapshotEntry],
    dry_run: bool,
) -> OperationResult:
    start = time.monotonic()
    result = OperationResult(operation="pull", dry_run=dry_run)
    actions = IncrementalActions(context)

    with context.lock_factory(
        context.lock_path,
        timeout=context.lock_timeout,
        operation="pull",
    ):
        logger.info("pull incremental changes.list started")
        local_snapshot = context.local.scan()
        baseline_by_drive_id = {
            entry.drive_id: entry
            for entry in baseline.values()
            if entry.drive_id
        }
        changes, new_token = context.drive.list_changes(token)
        logger.info("pull incremental applying %s Drive changes", len(changes))

        for change_index, change in enumerate(changes, start=1):
            file_id = change.get("fileId")
            old_entry = baseline_by_drive_id.get(file_id)
            removed = change.get("removed") or (
                change.get("file") or {}
            ).get("trashed")
            if removed:
                if old_entry:
                    actions.delete_local(
                        old_entry.path,
                        result,
                        dry_run=dry_run,
                    )
                    if not dry_run:
                        context.state.delete_baseline_path(
                            old_entry.path,
                            include_descendants=old_entry.type == "folder",
                        )
                continue

            entry, content, warning, failure = context.drive.entry_for_change(
                change,
                inspection_label=(
                    f"pull inspect cloud {change_index}/{len(changes)}"
                ),
            )
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
                    actions.delete_local(
                        old_entry.path,
                        result,
                        dry_run=dry_run,
                    )
                    if not dry_run:
                        context.state.delete_baseline_path(
                            old_entry.path,
                            include_descendants=old_entry.type == "folder",
                        )
                continue

            if old_entry and old_entry.path != entry.path:
                actions.delete_local(
                    old_entry.path,
                    result,
                    dry_run=dry_run,
                )
                if not dry_run:
                    context.state.delete_baseline_path(
                        old_entry.path,
                        include_descendants=old_entry.type == "folder",
                    )

            if entry.type == "folder":
                actions.apply_pull_folder(
                    entry,
                    local_snapshot,
                    result,
                    dry_run=dry_run,
                )
                if not dry_run:
                    context.state.upsert_baseline_entry(entry)
                should_walk_subtree = (
                    old_entry is None or old_entry.path != entry.path
                )
                if not should_walk_subtree:
                    continue
                for (
                    child_entry,
                    child_content,
                    child_warning,
                    child_failure,
                ) in context.drive.iter_subtree_with_content(
                    root_id=entry.drive_id or "",
                    root_path=entry.path,
                    local_snapshot=local_snapshot,
                ):
                    actions.apply_incremental_entry(
                        child_entry,
                        child_content,
                        child_warning,
                        child_failure,
                        local_snapshot,
                        result,
                        dry_run=dry_run,
                    )
                continue

            actions.apply_pull_file(
                entry,
                content,
                local_snapshot,
                result,
                dry_run=dry_run,
            )
            if not dry_run and not result.failures:
                context.state.upsert_baseline_entry(entry)

        if not dry_run and not result.failures:
            CheckpointManager(
                state=context.state,
                drive=context.drive,
            ).update_drive_token(new_token)
        result.elapsed_seconds = time.monotonic() - start

    if result.failures:
        raise SyncOperationFailed(
            "incremental pull completed with failures",
            partial_result=result,
        )
    return result


def run_incremental_sync(
    context,
    *,
    token: str,
    baseline: dict[str, SnapshotEntry],
    conflict_policy: ConflictPolicy,
    dry_run: bool,
) -> OperationResult:
    start = time.monotonic()
    result = OperationResult(operation="sync", dry_run=dry_run)
    actions = IncrementalActions(context)

    with context.lock_factory(
        context.lock_path,
        timeout=context.lock_timeout,
        operation="sync",
    ):
        logger.info("sync incremental local scan started")
        local_snapshot = context.local.scan()
        logger.info(
            "sync incremental local scan finished: entries=%s",
            len(local_snapshot),
        )
        local_changed = changed_paths(baseline, local_snapshot)

        logger.info("sync incremental changes.list started")
        baseline_by_drive_id = {
            entry.drive_id: entry
            for entry in baseline.values()
            if entry.drive_id
        }
        changes, new_token = context.drive.list_changes(token)
        cloud_entries: dict[str, SnapshotEntry] = {}
        cloud_content: dict[str, bytes] = {}
        cloud_deleted: set[str] = set()

        for change_index, change in enumerate(changes, start=1):
            file_id = change.get("fileId")
            old_entry = baseline_by_drive_id.get(file_id)
            removed = change.get("removed") or (
                change.get("file") or {}
            ).get("trashed")
            if removed:
                if old_entry:
                    cloud_deleted.add(old_entry.path)
                continue

            entry, content, warning, failure = context.drive.entry_for_change(
                change,
                inspection_label=(
                    f"sync inspect cloud {change_index}/{len(changes)}"
                ),
                include_content=False,
            )
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
            if content is not None:
                cloud_content[entry.path] = content

            if entry.type != "folder":
                continue
            should_walk_subtree = (
                old_entry is None or old_entry.path != entry.path
            )
            if not should_walk_subtree:
                continue
            for (
                child_entry,
                child_content,
                child_warning,
                child_failure,
            ) in context.drive.iter_subtree_with_content(
                root_id=entry.drive_id or "",
                root_path=entry.path,
                local_snapshot=local_snapshot,
                include_content=False,
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
                if child_content is not None:
                    cloud_content[child_entry.path] = child_content

        cloud_changed_paths = set(cloud_entries) | cloud_deleted
        affected_paths = collapse_local_folder_deletions(
            local_changed | cloud_changed_paths,
            local_changed=local_changed,
            cloud_changed=cloud_changed_paths,
            baseline=baseline,
            local_snapshot=local_snapshot,
        )
        logger.info(
            "sync incremental applying paths=%s local_changes=%s "
            "cloud_changes=%s cloud_deletes=%s",
            len(affected_paths),
            len(local_changed),
            len(cloud_entries),
            len(cloud_deleted),
        )
        progress = TransferProgress(
            total=incremental_transfer_count(
                affected_paths,
                local_changed=local_changed,
                cloud_changed=cloud_changed_paths,
                local_snapshot=local_snapshot,
                cloud_snapshot=cloud_entries,
                conflict_policy=conflict_policy,
            )
        )
        decisions = plan_incremental_changes(
            affected_paths,
            local_changed=local_changed,
            cloud_changed=cloud_changed_paths,
            conflict_policy=conflict_policy,
        )
        existing_paths = set(baseline) | set(local_snapshot) | set(cloud_entries)
        for decision in decisions:
            path = decision.path
            baseline_entry = baseline.get(path)
            local_entry = local_snapshot.get(path)

            if decision.conflict:
                if not _load_cloud_file(
                    context,
                    path,
                    cloud_entries,
                    cloud_content,
                    result,
                ):
                    continue
                actions.apply_conflict(
                    path,
                    baseline_entry,
                    local_entry,
                    cloud_entries.get(path),
                    cloud_content.get(path),
                    local_snapshot,
                    conflict_policy,
                    result,
                    progress,
                    existing_paths,
                    dry_run=dry_run,
                )
            elif decision.source == "local":
                actions.apply_local_change_to_cloud(
                    path,
                    local_entry,
                    baseline_entry,
                    result,
                    progress,
                    dry_run=dry_run,
                )
            else:
                if not _load_cloud_file(
                    context,
                    path,
                    cloud_entries,
                    cloud_content,
                    result,
                ):
                    continue
                actions.apply_cloud_change_to_local(
                    path,
                    cloud_entries.get(path),
                    cloud_content.get(path),
                    local_snapshot,
                    result,
                    progress,
                    dry_run=dry_run,
                )

        if not dry_run and not result.failures:
            for decision in decisions:
                if decision.source != "cloud":
                    continue
                entry = cloud_entries.get(decision.path)
                if entry is None:
                    baseline_entry = baseline.get(decision.path) or SnapshotEntry(
                        decision.path,
                        "file",
                    )
                    context.state.delete_baseline_path(
                        decision.path,
                        include_descendants=baseline_entry.type == "folder",
                    )
                else:
                    context.state.upsert_baseline_entry(entry)

            logger.info("sync incremental final changes.list started")
            tail_changes, tail_token = context.drive.list_changes(new_token)
            unexpected_ids = {
                change.get("fileId")
                for change in tail_changes
                if change.get("fileId") not in actions.cloud_mutation_ids
            }
            unexpected_ids.discard(None)
            checkpoint_token = tail_token
            if unexpected_ids:
                checkpoint_token = new_token
                message = (
                    "deferred "
                    f"{len(unexpected_ids)} Drive changes that arrived during sync"
                )
                logger.warning(message)
                result.warnings.append(message)
            CheckpointManager(
                state=context.state,
                drive=context.drive,
            ).update_drive_token(checkpoint_token)
        result.elapsed_seconds = time.monotonic() - start

    if result.failures:
        raise SyncOperationFailed(
            "incremental sync completed with failures",
            partial_result=result,
        )
    return result
