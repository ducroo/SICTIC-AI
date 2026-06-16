from __future__ import annotations

from .types import (
    ConflictPolicy,
    IncrementalDecision,
    SnapshotEntry,
)


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
            loser = (
                cloud_snapshot.get(path)
                if conflict_policy == "local-wins"
                else local_snapshot.get(path)
            )
            if loser is not None and loser.type == "file":
                total += 2
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
    phase = {
        ("local", False): 0,
        ("local", True): 1,
        ("cloud", True): 1,
        ("cloud", False): 2,
    }
    return sorted(
        decisions,
        key=lambda decision: (
            phase[(decision.source, decision.conflict)],
            decision.path,
        ),
    )
