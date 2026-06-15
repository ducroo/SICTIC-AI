from contextlib import nullcontext
from types import SimpleNamespace

from skills.gdrive_sync.full_sync import run_full_operation
from skills.gdrive_sync.incremental import run_incremental_pull
from skills.gdrive_sync.types import SnapshotEntry


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
