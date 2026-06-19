from __future__ import annotations

import logging
import time

from .actions import IncrementalActions
from .changes import materialize_cloud_changes, wait_for_drive_quiet
from .checkpoint import CheckpointManager
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
    TransferProgress,
)

logger = logging.getLogger(__name__)


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
        cloud = materialize_cloud_changes(
            context,
            token=token,
            baseline=baseline,
            result=result,
            include_content=True,
            label="pull",
            local_snapshot=local_snapshot,
        )
        logger.info("pull incremental applying %s Drive changes", len(cloud.changed_paths))

        for path in sorted(cloud.deleted):
            old_entry = baseline.get(path, SnapshotEntry(path, "file"))
            actions.delete_local(path, result, dry_run=dry_run)
            if not dry_run:
                context.state.delete_baseline_path(
                    path,
                    include_descendants=old_entry.type == "folder",
                )

        for entry in sorted(cloud.entries.values(), key=lambda item: item.path):
            if entry.type == "folder":
                actions.apply_pull_folder(
                    entry,
                    local_snapshot,
                    result,
                    dry_run=dry_run,
                )
                if not dry_run:
                    context.state.upsert_baseline_entry(entry)
                continue

            actions.apply_pull_file(
                entry,
                cloud.content.get(entry.path),
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
            ).update_drive_token(cloud.next_token)
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
        cloud = materialize_cloud_changes(
            context,
            token=token,
            baseline=baseline,
            result=result,
            include_content=True,
            label="sync",
            local_snapshot=local_snapshot,
        )
        cloud_changed_paths = cloud.changed_paths
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
            len(cloud.entries),
            len(cloud.deleted),
        )
        progress = TransferProgress(
            total=incremental_transfer_count(
                affected_paths,
                local_changed=local_changed,
                cloud_changed=cloud_changed_paths,
                local_snapshot=local_snapshot,
                cloud_snapshot=cloud.entries,
                conflict_policy=conflict_policy,
            )
        )
        decisions = plan_incremental_changes(
            affected_paths,
            local_changed=local_changed,
            cloud_changed=cloud_changed_paths,
            conflict_policy=conflict_policy,
        )
        existing_paths = set(baseline) | set(local_snapshot) | set(cloud.entries)
        for decision in decisions:
            path = decision.path
            baseline_entry = baseline.get(path)
            local_entry = local_snapshot.get(path)

            if decision.conflict:
                actions.apply_conflict(
                    path,
                    baseline_entry,
                    local_entry,
                    cloud.entries.get(path),
                    cloud.content.get(path),
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
                actions.apply_cloud_change_to_local(
                    path,
                    cloud.entries.get(path),
                    cloud.content.get(path),
                    local_snapshot,
                    result,
                    progress,
                    dry_run=dry_run,
                )

        if not dry_run and not result.failures:
            for decision in decisions:
                if decision.source != "cloud":
                    continue
                entry = cloud.entries.get(decision.path)
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

            logger.info("sync incremental quiet wait started")
            start_token = (
                context.drive.start_page_token()
                if hasattr(context.drive, "start_page_token")
                else None
            ) or cloud.next_token
            checkpoint_token = wait_for_drive_quiet(
                context,
                start_token=start_token,
                baseline=context.state.load_baseline(),
                mutations=actions.cloud_mutations,
                result=result,
                wait_seconds=getattr(context, "quiet_wait_seconds", 0.0),
            )
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
