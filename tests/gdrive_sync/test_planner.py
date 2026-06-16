from skills.gdrive_sync.planner import (
    plan_incremental_changes,
)
from skills.gdrive_sync.types import SnapshotEntry


def file(path, digest):
    return SnapshotEntry(path=path, type="file", sha256=digest, size=1, mtime=1.0)


def folder(path):
    return SnapshotEntry(path=path, type="folder")


def test_incremental_planner_marks_conflict_and_selected_winner():
    decisions = plan_incremental_changes(
        ["cloud.md", "conflict.md", "local.md"],
        local_changed={"conflict.md", "local.md"},
        cloud_changed={"cloud.md", "conflict.md"},
        conflict_policy="cloud-wins",
    )

    assert [(item.path, item.source, item.conflict) for item in decisions] == [
        ("local.md", "local", False),
        ("conflict.md", "cloud", True),
        ("cloud.md", "cloud", False),
    ]
