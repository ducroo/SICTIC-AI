from __future__ import annotations

import logging
import time

from .checkpoint import CheckpointManager, merged_baseline
from .executor import TransferProgress
from .planner import plan_pull, plan_push, plan_sync
from .types import (
    ConflictPolicy,
    OperationResult,
    SnapshotEntry,
    SyncOperationFailed,
)

logger = logging.getLogger(__name__)


def run_full_operation(
    context,
    operation: str,
    *,
    conflict_policy: ConflictPolicy,
    dry_run: bool,
) -> OperationResult:
    start = time.monotonic()
    result = OperationResult(operation=operation, dry_run=dry_run)
    with context.lock_factory(
        context.lock_path,
        timeout=context.lock_timeout,
        operation=operation,
    ):
        baseline = context.state.load_baseline()
        logger.info("%s local scan started", operation)
        local_snapshot = context.local.scan()
        logger.info(
            "%s local scan finished: entries=%s",
            operation,
            len(local_snapshot),
        )
        cloud_snapshot, warnings, failures = context.drive.scan()
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
        progress = TransferProgress(
            total=sum(action.action in {"copy", "copy_as"} for action in actions)
        )
        for action in actions:
            context.executor.apply(
                action,
                result,
                dry_run=dry_run,
                progress=progress,
            )

        if not dry_run and not result.failures:
            logger.info("%s committing baseline", operation)
            if operation == "pull":
                final_baseline = dict(cloud_snapshot)
            elif operation == "push":
                final_baseline = dict(local_snapshot)
            else:
                local_snapshot = context.local.scan()
                cloud_snapshot, warnings, failures = context.drive.scan()
                result.warnings.extend(warnings)
                result.failures.extend(failures)
                final_baseline = merged_baseline(local_snapshot, cloud_snapshot)
            if not result.failures:
                CheckpointManager(
                    state=context.state,
                    drive=context.drive,
                ).commit_full_baseline(final_baseline)
        result.elapsed_seconds = time.monotonic() - start

    if result.failures:
        raise SyncOperationFailed(
            f"{operation} completed with failures",
            partial_result=result,
        )
    return result


def run_streaming_pull(context, *, dry_run: bool) -> OperationResult:
    start = time.monotonic()
    result = OperationResult(operation="pull", dry_run=dry_run)
    checkpoints = CheckpointManager(state=context.state, drive=context.drive)

    with context.lock_factory(
        context.lock_path,
        timeout=context.lock_timeout,
        operation="pull",
    ):
        operation_id = checkpoints.begin_or_resume_pull(dry_run=dry_run)
        logger.info("pull local scan started")
        local_snapshot = context.local.scan()
        logger.info("pull local scan finished: entries=%s", len(local_snapshot))
        checkpoint = (
            context.state.load_checkpoint(operation_id)
            if not dry_run
            else {}
        )
        if checkpoint:
            logger.info("pull loaded checkpoint entries=%s", len(checkpoint))

        progress = TransferProgress(total=context.drive.count_files())
        cloud_snapshot: dict[str, SnapshotEntry] = {}
        for entry, content, warning, failure in context.drive.iter_entries_with_content(
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
                        result.skipped_entries.append(
                            f"dry-run:mkdir:{entry.path}"
                        )
                    else:
                        context.local.mkdir(entry.path)
                    result.created_folders.append(entry.path)
                if not dry_run:
                    context.state.save_checkpoint_entry(operation_id, entry)
                continue

            if (
                local_entry is not None
                and local_entry.type == "file"
                and local_entry.sha256 == entry.sha256
            ):
                result.skipped_entries.append(entry.path)
                if not dry_run:
                    context.state.save_checkpoint_entry(operation_id, entry)
                continue
            if content is None:
                result.failures.append(
                    f"{entry.path}: Drive file yielded no content"
                )
                continue

            progress.log("download", entry.path, len(content))
            if dry_run:
                result.skipped_entries.append(f"dry-run:write:{entry.path}")
            else:
                context.local.write_bytes_atomic(entry.path, content)
                context.state.save_checkpoint_entry(operation_id, entry)
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
                context.local.remove(path)
                context.local.prune_empty_parents(path)
            result.deleted_entries.append(path)

        if not dry_run and not result.failures:
            logger.info("pull committing baseline")
            checkpoints.commit_streaming_pull(operation_id)
        result.elapsed_seconds = time.monotonic() - start

    if result.failures:
        raise SyncOperationFailed(
            "pull completed with failures",
            partial_result=result,
        )
    return result
