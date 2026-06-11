from gdrive_sync.planner import plan_push, plan_sync
from gdrive_sync.types import SnapshotEntry


def file(path, digest):
    return SnapshotEntry(path=path, type="file", sha256=digest, size=1, mtime=1.0)


def folder(path):
    return SnapshotEntry(path=path, type="folder")


def test_push_mirrors_local_to_cloud():
    actions = plan_push(
        {"a": folder("a"), "a/file.md": file("a/file.md", "1")},
        {"old.md": file("old.md", "2")},
    )

    assert [a.action for a in actions] == ["mkdir", "copy", "delete"]
    assert actions[0].path == "a"
    assert actions[1].source == "local"
    assert actions[1].target == "cloud"
    assert actions[2].path == "old.md"


def test_sync_local_only_change_copies_to_cloud():
    actions = plan_sync(
        {"a.md": file("a.md", "1")},
        {"a.md": file("a.md", "2")},
        {"a.md": file("a.md", "1")},
        conflict_policy="local-wins",
    )

    assert len(actions) == 1
    assert actions[0].action == "copy"
    assert actions[0].source == "local"
    assert actions[0].target == "cloud"


def test_sync_content_conflict_local_wins_preserves_cloud_copy():
    actions = plan_sync(
        {"a.md": file("a.md", "1")},
        {"a.md": file("a.md", "2")},
        {"a.md": file("a.md", "3")},
        conflict_policy="local-wins",
    )

    copy_as = [a for a in actions if a.action == "copy_as"]
    canonical = [a for a in actions if a.action == "copy"]
    assert {a.target for a in copy_as} == {"local", "cloud"}
    assert copy_as[0].conflict_path == "a.conflict-cloud.md"
    assert canonical[0].source == "local"
    assert canonical[0].target == "cloud"
