from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from gdrive_sync.client import GDriveSync
from gdrive_sync.types import SnapshotEntry, SyncOperationFailed


def test_incremental_upload_failure_does_not_stop_following_file(monkeypatch):
    syncer = GDriveSync.__new__(GDriveSync)
    contents = {
        "a-too-large.md": b"x" * 10,
        "z-next.md": b"ok",
    }
    uploaded = []
    baselined = []
    baseline = {
        path: SnapshotEntry(path=path, type="file", sha256="old")
        for path in contents
    }
    local_snapshot = {
        path: SnapshotEntry(path=path, type="file", sha256="new")
        for path in contents
    }

    syncer.local = SimpleNamespace(
        read_bytes=lambda path: contents[path],
        scan=lambda: local_snapshot,
    )

    def write_bytes(path, content):
        if path == "a-too-large.md":
            raise ValueError("Google Doc upload safety limit exceeded")
        uploaded.append((path, content))

    syncer.drive = SimpleNamespace(
        write_bytes=write_bytes,
        list_changes=lambda _token: ([], "new-token"),
        entry_after_write=lambda path, content: SnapshotEntry(
            path=path,
            type="file",
            size=len(content),
        ),
    )
    syncer.state = SimpleNamespace(
        upsert_baseline_entry=baselined.append,
    )
    syncer.lock_path = "unused"
    syncer.lock_timeout = 1
    monkeypatch.setattr(
        "gdrive_sync.client.PairingLock",
        lambda *_args, **_kwargs: nullcontext(),
    )

    with pytest.raises(SyncOperationFailed) as error:
        syncer._run_sync_incremental(
            token="token",
            baseline=baseline,
            conflict_policy="local-wins",
            dry_run=False,
        )

    result = error.value.partial_result
    assert result.failures == [
        "a-too-large.md: Google Doc upload safety limit exceeded",
    ]
    assert uploaded == [("z-next.md", b"ok")]
    assert [entry.path for entry in baselined] == ["z-next.md"]
    assert result.updated_files == ["z-next.md"]
    assert result.bytes_transferred == 2
