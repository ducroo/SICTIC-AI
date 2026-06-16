from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from .types import CloudMutations, OperationResult, SnapshotEntry

logger = logging.getLogger(__name__)


@dataclass
class CloudChanges:
    entries: dict[str, SnapshotEntry] = field(default_factory=dict)
    content: dict[str, bytes] = field(default_factory=dict)
    deleted: set[str] = field(default_factory=set)
    drive_ids: set[str] = field(default_factory=set)
    paths_by_id: dict[str, str] = field(default_factory=dict)
    next_token: str = ""

    @property
    def changed_paths(self) -> set[str]:
        return set(self.entries) | self.deleted


def baseline_by_drive_id(
    baseline: dict[str, SnapshotEntry],
) -> dict[str, SnapshotEntry]:
    return {
        entry.drive_id: entry
        for entry in baseline.values()
        if entry.drive_id
    }


def materialize_cloud_changes(
    context,
    *,
    token: str,
    baseline: dict[str, SnapshotEntry],
    result: OperationResult,
    include_content: bool = True,
    label: str,
    local_snapshot: dict[str, SnapshotEntry] | None = None,
) -> CloudChanges:
    changes, next_token = context.drive.list_changes(token)
    cloud = CloudChanges(next_token=next_token)
    old_by_id = baseline_by_drive_id(baseline)
    total = len(changes)

    for change_index, change in enumerate(changes, start=1):
        file_id = change.get("fileId")
        if file_id:
            cloud.drive_ids.add(file_id)
        old_entry = old_by_id.get(file_id)
        removed = change.get("removed") or (
            change.get("file") or {}
        ).get("trashed")
        if removed:
            if old_entry:
                cloud.deleted.add(old_entry.path)
                if file_id:
                    cloud.paths_by_id[file_id] = old_entry.path
            continue

        entry, content, warning, failure = context.drive.entry_for_change(
            change,
            inspection_label=f"{label} inspect cloud {change_index}/{total}",
            include_content=include_content,
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
                cloud.deleted.add(old_entry.path)
                if file_id:
                    cloud.paths_by_id[file_id] = old_entry.path
            continue
        if old_entry and old_entry.path != entry.path:
            cloud.deleted.add(old_entry.path)

        cloud.entries[entry.path] = entry
        if entry.drive_id:
            cloud.paths_by_id[entry.drive_id] = entry.path
        if content is not None:
            cloud.content[entry.path] = content

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
            include_content=include_content,
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
            cloud.entries[child_entry.path] = child_entry
            if child_entry.drive_id:
                cloud.drive_ids.add(child_entry.drive_id)
                cloud.paths_by_id[child_entry.drive_id] = child_entry.path
            if child_content is not None:
                cloud.content[child_entry.path] = child_content

    return cloud


def _change_path(context, change: dict, baseline: dict[str, SnapshotEntry]) -> str | None:
    file_id = change.get("fileId")
    if file_id:
        old_entry = baseline_by_drive_id(baseline).get(file_id)
        if old_entry:
            return old_entry.path
    if not hasattr(context.drive, "entry_for_change"):
        return None
    entry, _content, warning, failure = context.drive.entry_for_change(
        change,
        include_content=False,
    )
    if warning:
        logger.warning(warning)
    if failure:
        logger.warning(failure)
    return entry.path if entry is not None else None


def _is_self_generated_change(
    context,
    change: dict,
    *,
    baseline: dict[str, SnapshotEntry],
    mutations: CloudMutations,
) -> bool:
    file_id = change.get("fileId")
    if file_id and file_id in mutations.drive_ids:
        return True
    path = _change_path(context, change, baseline)
    return bool(path and path in mutations.paths)


def wait_for_drive_quiet(
    context,
    *,
    start_token: str,
    baseline: dict[str, SnapshotEntry],
    mutations: CloudMutations,
    result: OperationResult,
    wait_seconds: float = 5.0,
) -> str:
    safe_token = start_token
    token = start_token
    while True:
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        result.quiet_wait_rounds += 1
        changes, next_token = context.drive.list_changes(token)
        if not changes:
            return next_token

        external = [
            change
            for change in changes
            if not _is_self_generated_change(
                context,
                change,
                baseline=baseline,
                mutations=mutations,
            )
        ]
        if external:
            result.external_drive_changes_after_sync += len(external)
            message = (
                f"deferred {len(external)} Drive changes that arrived during sync"
            )
            logger.warning(message)
            result.warnings.append(message)
            return safe_token

        result.self_generated_drive_changes += len(changes)
        safe_token = next_token
        token = next_token
