from __future__ import annotations

from .types import (
    ConflictPolicy,
    IncrementalDecision,
    PlannedAction,
    SnapshotEntry,
)
from .util import conflict_name


def _changed(current: SnapshotEntry | None, baseline: SnapshotEntry | None) -> bool:
    if current is None:
        return baseline is not None
    if baseline is None:
        return True
    if current.type != baseline.type:
        return True
    if current.type == "folder":
        return False
    return current.sha256 != baseline.sha256


def changed_paths(
    baseline: dict[str, SnapshotEntry],
    current: dict[str, SnapshotEntry],
) -> set[str]:
    return {
        path
        for path in set(baseline) | set(current)
        if _changed(current.get(path), baseline.get(path))
    }


def collapse_local_folder_deletions(
    paths: set[str],
    *,
    local_changed: set[str],
    cloud_changed: set[str],
    baseline: dict[str, SnapshotEntry],
    local_snapshot: dict[str, SnapshotEntry],
) -> list[str]:
    deleted_roots: list[str] = []
    for path in sorted(local_changed, key=lambda item: (item.count("/"), item)):
        base = baseline.get(path)
        if (
            local_snapshot.get(path) is not None
            or base is None
            or base.type != "folder"
            or any(
                changed == path or changed.startswith(f"{path}/")
                for changed in cloud_changed
            )
            or any(path.startswith(f"{root}/") for root in deleted_roots)
        ):
            continue
        deleted_roots.append(path)

    return sorted(
        path
        for path in paths
        if path in cloud_changed
        or not any(path.startswith(f"{root}/") for root in deleted_roots)
    )


def incremental_transfer_count(
    paths: list[str],
    *,
    local_changed: set[str],
    cloud_changed: set[str],
    local_snapshot: dict[str, SnapshotEntry],
    cloud_snapshot: dict[str, SnapshotEntry],
    conflict_policy: ConflictPolicy,
) -> int:
    total = 0
    for path in paths:
        has_local_change = path in local_changed
        has_cloud_change = path in cloud_changed
        if has_local_change and has_cloud_change:
            winner = (
                local_snapshot.get(path)
                if conflict_policy == "local-wins"
                else cloud_snapshot.get(path)
            )
        elif has_local_change:
            winner = local_snapshot.get(path)
        else:
            winner = cloud_snapshot.get(path)
        if winner is not None and winner.type == "file":
            total += 1
    return total


def plan_incremental_changes(
    paths: list[str],
    *,
    local_changed: set[str],
    cloud_changed: set[str],
    conflict_policy: ConflictPolicy,
) -> list[IncrementalDecision]:
    decisions: list[IncrementalDecision] = []
    for path in paths:
        has_local_change = path in local_changed
        has_cloud_change = path in cloud_changed
        if has_local_change and has_cloud_change:
            decisions.append(
                IncrementalDecision(
                    path=path,
                    source="local" if conflict_policy == "local-wins" else "cloud",
                    conflict=True,
                )
            )
        elif has_local_change:
            decisions.append(IncrementalDecision(path=path, source="local"))
        elif has_cloud_change:
            decisions.append(IncrementalDecision(path=path, source="cloud"))
    return decisions


def _same(a: SnapshotEntry | None, b: SnapshotEntry | None) -> bool:
    if a is None or b is None:
        return a is b
    if a.type != b.type:
        return False
    if a.type == "folder":
        return True
    return a.sha256 == b.sha256


def plan_push(local: dict[str, SnapshotEntry], cloud: dict[str, SnapshotEntry]) -> list[PlannedAction]:
    actions: list[PlannedAction] = []
    for path in sorted(local):
        entry = local[path]
        if entry.type == "folder":
            if path not in cloud:
                actions.append(PlannedAction("mkdir", path, source="local", target="cloud"))
            continue
        if not _same(entry, cloud.get(path)):
            actions.append(PlannedAction("copy", path, source="local", target="cloud"))
    for path in sorted(set(cloud) - set(local), reverse=True):
        actions.append(PlannedAction("delete", path, target="cloud"))
    return actions


def plan_pull(local: dict[str, SnapshotEntry], cloud: dict[str, SnapshotEntry]) -> list[PlannedAction]:
    actions: list[PlannedAction] = []
    for path in sorted(cloud):
        entry = cloud[path]
        if entry.type == "folder":
            if path not in local:
                actions.append(PlannedAction("mkdir", path, source="cloud", target="local"))
            continue
        if not _same(entry, local.get(path)):
            actions.append(PlannedAction("copy", path, source="cloud", target="local"))
    for path in sorted(set(local) - set(cloud), reverse=True):
        actions.append(PlannedAction("delete", path, target="local"))
    return actions


def plan_sync(
    baseline: dict[str, SnapshotEntry],
    local: dict[str, SnapshotEntry],
    cloud: dict[str, SnapshotEntry],
    *,
    conflict_policy: ConflictPolicy,
) -> list[PlannedAction]:
    actions: list[PlannedAction] = []
    existing = set(local) | set(cloud)
    for path in sorted(set(baseline) | set(local) | set(cloud)):
        base = baseline.get(path)
        left = local.get(path)
        right = cloud.get(path)
        local_changed = _changed(left, base)
        cloud_changed = _changed(right, base)
        if not local_changed and not cloud_changed:
            continue
        if local_changed and not cloud_changed:
            if left is None:
                actions.append(PlannedAction("delete", path, target="cloud"))
            elif left.type == "folder":
                actions.append(PlannedAction("mkdir", path, source="local", target="cloud"))
            else:
                actions.append(PlannedAction("copy", path, source="local", target="cloud"))
            continue
        if cloud_changed and not local_changed:
            if right is None:
                actions.append(PlannedAction("delete", path, target="local"))
            elif right.type == "folder":
                actions.append(PlannedAction("mkdir", path, source="cloud", target="local"))
            else:
                actions.append(PlannedAction("copy", path, source="cloud", target="local"))
            continue
        if _same(left, right):
            continue
        if conflict_policy == "local-wins":
            if left is None:
                if right is not None and right.type == "file":
                    conflict = conflict_name(path, "conflict-cloud", existing)
                    actions.append(PlannedAction("copy_as", path, source="cloud", target="local", conflict_path=conflict))
                    actions.append(PlannedAction("copy_as", path, source="cloud", target="cloud", conflict_path=conflict))
                actions.append(PlannedAction("delete", path, target="cloud"))
            elif right is None:
                if left.type == "folder":
                    actions.append(PlannedAction("mkdir", path, source="local", target="cloud"))
                else:
                    actions.append(PlannedAction("copy", path, source="local", target="cloud"))
            else:
                if right.type == "file":
                    conflict = conflict_name(path, "conflict-cloud", existing)
                    actions.append(PlannedAction("copy_as", path, source="cloud", target="local", conflict_path=conflict))
                    actions.append(PlannedAction("copy_as", path, source="cloud", target="cloud", conflict_path=conflict))
                if left.type == "folder":
                    actions.append(PlannedAction("mkdir", path, source="local", target="cloud"))
                else:
                    actions.append(PlannedAction("copy", path, source="local", target="cloud"))
            actions.append(PlannedAction("conflict", path, message="local-wins"))
        else:
            if right is None:
                if left is not None and left.type == "file":
                    conflict = conflict_name(path, "conflict-local", existing)
                    actions.append(PlannedAction("copy_as", path, source="local", target="cloud", conflict_path=conflict))
                    actions.append(PlannedAction("copy_as", path, source="local", target="local", conflict_path=conflict))
                actions.append(PlannedAction("delete", path, target="local"))
            elif left is None:
                if right.type == "folder":
                    actions.append(PlannedAction("mkdir", path, source="cloud", target="local"))
                else:
                    actions.append(PlannedAction("copy", path, source="cloud", target="local"))
            else:
                if left.type == "file":
                    conflict = conflict_name(path, "conflict-local", existing)
                    actions.append(PlannedAction("copy_as", path, source="local", target="cloud", conflict_path=conflict))
                    actions.append(PlannedAction("copy_as", path, source="local", target="local", conflict_path=conflict))
                if right.type == "folder":
                    actions.append(PlannedAction("mkdir", path, source="cloud", target="local"))
                else:
                    actions.append(PlannedAction("copy", path, source="cloud", target="local"))
            actions.append(PlannedAction("conflict", path, message="cloud-wins"))
    return actions
