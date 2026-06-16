from __future__ import annotations

import logging
import time

from .checkpoint import CheckpointManager
from .types import OperationResult, SnapshotEntry, SyncOperationFailed, TransferProgress

logger = logging.getLogger(__name__)


def run_bootstrap_pull(context, *, dry_run: bool) -> OperationResult:
    """Force the local mirror to match Drive and establish a baseline."""
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
