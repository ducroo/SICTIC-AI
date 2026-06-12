from __future__ import annotations

from .types import ConflictPolicy, PlannedAction, SnapshotEntry
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
