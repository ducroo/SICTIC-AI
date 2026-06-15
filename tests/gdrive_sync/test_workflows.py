from contextlib import nullcontext
from types import SimpleNamespace

from skills.gdrive_sync.actions import IncrementalActions
from skills.gdrive_sync.executor import TransferProgress
from skills.gdrive_sync.full_sync import run_full_operation
from skills.gdrive_sync.incremental import (
    run_incremental_pull,
    run_incremental_sync,
)
from skills.gdrive_sync.local import LocalTree
from skills.gdrive_sync.types import OperationResult, SnapshotEntry
from skills.gdrive_sync.util import sha256_bytes


class _State:
    def __init__(self, baseline=None):
        self.baseline = baseline or {}
        self.saved_baseline = None
        self.metadata = {}

    def load_baseline(self):
        return self.baseline

    def save_baseline(self, entries):
        self.saved_baseline = entries

    def set_metadata(self, key, value):
        self.metadata[key] = value

    def upsert_baseline_entry(self, entry):
        self.baseline[entry.path] = entry

    def delete_baseline_path(self, path, *, include_descendants=False):
        self.baseline.pop(path, None)
        if include_descendants:
            for child in list(self.baseline):
                if child.startswith(f"{path}/"):
                    self.baseline.pop(child)


def _context(*, local, drive, state, executor=None):
    return SimpleNamespace(
        local=local,
        drive=drive,
        state=state,
        executor=executor,
        lock_path="unused",
        lock_timeout=1,
        lock_factory=lambda *_args, **_kwargs: nullcontext(),
    )


def test_full_push_commits_local_snapshot_and_drive_token():
    local_snapshot = {
        "file.md": SnapshotEntry(
            path="file.md",
            type="file",
            sha256="local",
        )
    }
    applied = []
    state = _State()
    context = _context(
        local=SimpleNamespace(scan=lambda: local_snapshot),
        drive=SimpleNamespace(
            scan=lambda: ({}, [], []),
            start_page_token=lambda: "token-2",
        ),
        state=state,
        executor=SimpleNamespace(
            apply=lambda action, *_args, **_kwargs: applied.append(action)
        ),
    )

    result = run_full_operation(
        context,
        "push",
        conflict_policy="local-wins",
        dry_run=False,
    )

    assert result.ok
    assert [(action.action, action.path) for action in applied] == [
        ("copy", "file.md")
    ]
    assert state.saved_baseline == local_snapshot
    assert state.metadata["drive_start_page_token"] == "token-2"


def test_incremental_pull_advances_changes_token_when_no_files_changed():
    state = _State()
    context = _context(
        local=SimpleNamespace(scan=lambda: {}),
        drive=SimpleNamespace(
            list_changes=lambda _token: ([], "token-2"),
        ),
        state=state,
    )

    result = run_incremental_pull(
        context,
        token="token-1",
        baseline={
            "existing.md": SnapshotEntry(
                path="existing.md",
                type="file",
                drive_id="drive-1",
            )
        },
        dry_run=False,
    )

    assert result.ok
    assert state.metadata["drive_start_page_token"] == "token-2"


def test_incremental_sync_orders_phases_and_mirrors_conflict(tmp_path):
    operations = []
    local = LocalTree(tmp_path)
    local.write_bytes_atomic("local.md", b"local-new")
    local.write_bytes_atomic("conflict.md", b"local-winner")
    local.write_bytes_atomic("cloud.md", b"cloud-old")

    original_local_write = local.write_bytes_atomic

    def logged_local_write(path, content):
        operations.append(("local-write", path))
        original_local_write(path, content)

    local.write_bytes_atomic = logged_local_write
    baseline = {
        "local.md": SnapshotEntry(
            "local.md",
            "file",
            sha256=sha256_bytes(b"local-old"),
            drive_id="local-id",
        ),
        "conflict.md": SnapshotEntry(
            "conflict.md",
            "file",
            sha256=sha256_bytes(b"conflict-old"),
            drive_id="conflict-id",
        ),
        "cloud.md": SnapshotEntry(
            "cloud.md",
            "file",
            sha256=sha256_bytes(b"cloud-old"),
            drive_id="cloud-id",
        ),
    }
    cloud_entries = {
        "conflict-id": (
            SnapshotEntry(
                "conflict.md",
                "file",
                sha256=sha256_bytes(b"cloud-loser"),
                drive_id="conflict-id",
            ),
            b"cloud-loser",
        ),
        "cloud-id": (
            SnapshotEntry(
                "cloud.md",
                "file",
                sha256=sha256_bytes(b"cloud-new"),
                drive_id="cloud-id",
            ),
            b"cloud-new",
        ),
    }
    cloud_content = {
        "local.md": b"local-old",
        "conflict.md": b"cloud-loser",
        "cloud.md": b"cloud-new",
    }
    drive_ids = {
        "local.md": "local-id",
        "conflict.md": "conflict-id",
        "cloud.md": "cloud-id",
    }
    list_calls = 0

    def list_changes(token):
        nonlocal list_calls
        list_calls += 1
        if list_calls == 1:
            assert token == "token-1"
            return (
                [
                    {"fileId": "conflict-id", "file": {"name": "conflict.md"}},
                    {"fileId": "cloud-id", "file": {"name": "cloud.md"}},
                ],
                "token-2",
            )
        assert token == "token-2"
        return (
            [
                {"fileId": "local-id"},
                {"fileId": "conflict-copy-id"},
                {"fileId": "conflict-id"},
            ],
            "token-3",
        )

    def write_cloud(path, content):
        operations.append(("cloud-write", path))
        cloud_content[path] = content
        drive_ids.setdefault(path, "conflict-copy-id")

    def entry_for_change(change, *, include_content=True, **_kwargs):
        entry, content = cloud_entries[change["fileId"]]
        return entry, content if include_content else None, None, None

    def read_cloud(path):
        operations.append(("cloud-read", path))
        return cloud_content[path]

    drive = SimpleNamespace(
        list_changes=list_changes,
        entry_for_change=entry_for_change,
        read_bytes=read_cloud,
        write_bytes=write_cloud,
        entry_after_write=lambda path, content: SnapshotEntry(
            path,
            "file",
            sha256=sha256_bytes(content),
            drive_id=drive_ids[path],
        ),
        mkdir=lambda _path: None,
        remove=lambda path: operations.append(("cloud-delete", path)),
    )
    state = _State(dict(baseline))

    result = run_incremental_sync(
        _context(local=local, drive=drive, state=state),
        token="token-1",
        baseline=baseline,
        conflict_policy="local-wins",
        dry_run=False,
    )

    assert result.ok
    assert operations == [
        ("cloud-write", "local.md"),
        ("cloud-read", "conflict.md"),
        ("local-write", "conflict.conflict-cloud.md"),
        ("cloud-write", "conflict.conflict-cloud.md"),
        ("cloud-write", "conflict.md"),
        ("cloud-read", "cloud.md"),
        ("local-write", "cloud.md"),
    ]
    assert local.read_bytes("conflict.conflict-cloud.md") == b"cloud-loser"
    assert cloud_content["conflict.conflict-cloud.md"] == b"cloud-loser"
    assert cloud_content["conflict.md"] == b"local-winner"
    assert local.read_bytes("cloud.md") == b"cloud-new"
    assert state.metadata["drive_start_page_token"] == "token-3"


def test_incremental_sync_does_not_skip_concurrent_cloud_change(tmp_path):
    local = LocalTree(tmp_path)
    local.write_bytes_atomic("local.md", b"local-new")
    baseline = {
        "local.md": SnapshotEntry(
            "local.md",
            "file",
            sha256=sha256_bytes(b"local-old"),
            drive_id="local-id",
        )
    }
    calls = iter(
        [
            ([], "token-2"),
            ([{"fileId": "external-id"}], "token-3"),
        ]
    )
    drive = SimpleNamespace(
        list_changes=lambda _token: next(calls),
        write_bytes=lambda _path, _content: None,
        entry_after_write=lambda path, content: SnapshotEntry(
            path,
            "file",
            sha256=sha256_bytes(content),
            drive_id="local-id",
        ),
    )
    state = _State(dict(baseline))

    result = run_incremental_sync(
        _context(local=local, drive=drive, state=state),
        token="token-1",
        baseline=baseline,
        conflict_policy="local-wins",
        dry_run=False,
    )

    assert result.ok
    assert state.metadata["drive_start_page_token"] == "token-2"
    assert result.warnings == [
        "deferred 1 Drive changes that arrived during sync"
    ]


def test_incremental_cloud_wins_preserves_local_conflict_on_both_sides(
    tmp_path,
):
    local = LocalTree(tmp_path)
    local.write_bytes_atomic("conflict.md", b"local-loser")
    cloud_content = {}
    state = _State()
    drive = SimpleNamespace(
        mkdir=lambda _path: None,
        write_bytes=lambda path, content: cloud_content.__setitem__(
            path,
            content,
        ),
        entry_after_write=lambda path, content: SnapshotEntry(
            path,
            "file",
            sha256=sha256_bytes(content),
            drive_id="conflict-copy-id",
        ),
    )
    actions = IncrementalActions(
        _context(local=local, drive=drive, state=state)
    )
    result = OperationResult(operation="sync")
    cloud_entry = SnapshotEntry(
        "conflict.md",
        "file",
        sha256=sha256_bytes(b"cloud-winner"),
        drive_id="conflict-id",
    )

    actions.apply_conflict(
        "conflict.md",
        SnapshotEntry("conflict.md", "file", drive_id="conflict-id"),
        SnapshotEntry(
            "conflict.md",
            "file",
            sha256=sha256_bytes(b"local-loser"),
        ),
        cloud_entry,
        b"cloud-winner",
        {"conflict.md": SnapshotEntry("conflict.md", "file")},
        "cloud-wins",
        result,
        TransferProgress(total=3),
        {"conflict.md"},
        dry_run=False,
    )

    assert result.failures == []
    assert local.read_bytes("conflict.conflict-local.md") == b"local-loser"
    assert cloud_content["conflict.conflict-local.md"] == b"local-loser"
    assert local.read_bytes("conflict.md") == b"cloud-winner"
