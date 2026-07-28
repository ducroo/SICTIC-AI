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
        validate_cloud_mutations=lambda _mutations: None,
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


def test_incremental_sync_parent_preflight_stops_before_cloud_mutations(monkeypatch):
    syncer = GDriveSync.__new__(GDriveSync)
    baseline = {
        "storage/startups/proud-technology/old.pdf": SnapshotEntry(
            path="storage/startups/proud-technology/old.pdf",
            type="file",
            sha256="old",
        ),
        "storage/startups/proud-technology/new-room": SnapshotEntry(
            path="storage/startups/proud-technology/new-room",
            type="folder",
        ),
    }
    local_snapshot = {
        "storage/startups/proud-technology/new-room": SnapshotEntry(
            path="storage/startups/proud-technology/new-room",
            type="folder",
        ),
        "storage/startups/proud-technology/new-room/new.pdf": SnapshotEntry(
            path="storage/startups/proud-technology/new-room/new.pdf",
            type="file",
            sha256="new",
        ),
    }
    cloud_mutations = []

    syncer.local = SimpleNamespace(
        scan=lambda: local_snapshot,
        read_bytes=lambda _path: b"new",
    )

    def reject_shortcut_parent(mutations):
        cloud_mutations.extend(mutations)
        raise NotADirectoryError(
            "storage/startups/proud-technology: a Google Drive shortcut blocks "
            "the synchronized path"
        )

    syncer.drive = SimpleNamespace(
        list_changes=lambda _token: ([], "new-token"),
        validate_cloud_mutations=reject_shortcut_parent,
        remove=lambda path: pytest.fail(f"must not delete before preflight: {path}"),
        mkdir=lambda path: pytest.fail(f"must not create before preflight: {path}"),
        write_bytes=lambda path, content: pytest.fail(
            f"must not upload before preflight: {path}"
        ),
    )
    syncer.state = SimpleNamespace()
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

    assert "Google Drive shortcut" in error.value.partial_result.failures[0]
    assert cloud_mutations


def test_incremental_pull_shortcut_preflight_stops_before_local_mutations(
    monkeypatch,
):
    syncer = GDriveSync.__new__(GDriveSync)
    baseline = {
        "old.md": SnapshotEntry(
            path="old.md",
            type="file",
            sha256="old",
            drive_id="old-id",
        )
    }
    syncer.local = SimpleNamespace(
        scan=lambda: baseline,
        remove=lambda path: pytest.fail(f"must not delete before preflight: {path}"),
        prune_empty_parents=lambda path: None,
    )

    def entry_for_change(change, *, include_content=True):
        assert include_content is False
        return (
            None,
            None,
            None,
            "startups/proud-technology: Google Drive shortcuts are not supported",
        )

    syncer.drive = SimpleNamespace(
        list_changes=lambda _token: (
            [
                {"fileId": "old-id", "removed": True},
                {
                    "fileId": "shortcut-id",
                    "file": {
                        "id": "shortcut-id",
                        "name": "proud-technology",
                        "mimeType": "application/vnd.google-apps.shortcut",
                    },
                },
            ],
            "new-token",
        ),
        entry_for_change=entry_for_change,
    )
    syncer.state = SimpleNamespace(
        delete_baseline_path=lambda *args, **kwargs: pytest.fail(
            "must not update baseline before preflight"
        ),
    )
    syncer.lock_path = "unused"
    syncer.lock_timeout = 1
    monkeypatch.setattr(
        "gdrive_sync.client.PairingLock",
        lambda *_args, **_kwargs: nullcontext(),
    )

    with pytest.raises(SyncOperationFailed) as error:
        syncer._run_pull_incremental(
            token="token",
            baseline=baseline,
            dry_run=False,
        )

    assert "shortcuts are not supported" in error.value.partial_result.failures[0]


def test_incremental_cloud_wins_skips_local_and_cloud_deletes(monkeypatch):
    syncer = GDriveSync.__new__(GDriveSync)
    baseline = {
        "keep-local.md": SnapshotEntry(path="keep-local.md", type="file", sha256="1", drive_id="cloud-1"),
        "local-only.md": SnapshotEntry(path="local-only.md", type="file", sha256="1"),
    }
    local_snapshot = {
        "keep-local.md": SnapshotEntry(path="keep-local.md", type="file", sha256="1"),
    }
    deleted = []
    uploaded = []
    written = []

    syncer.local = SimpleNamespace(
        read_bytes=lambda path: b"local",
        scan=lambda: local_snapshot,
        write_bytes_atomic=lambda path, content: written.append((path, content)),
        mkdir=lambda path: None,
        remove=lambda path: deleted.append(path),
        prune_empty_parents=lambda path: None,
    )
    syncer.drive = SimpleNamespace(
        remove=lambda path: deleted.append(f"cloud:{path}"),
        write_bytes=lambda path, content: uploaded.append((path, content)),
        list_changes=lambda _token: (
            [
                {"fileId": "cloud-1", "removed": True},
                {
                    "fileId": "cloud-2",
                    "file": {"id": "cloud-2", "name": "new-cloud.md", "mimeType": "text/markdown"},
                },
            ],
            "new-token",
        ),
        entry_for_change=lambda change: (
            (
                SnapshotEntry(
                    path="new-cloud.md",
                    type="file",
                    sha256="new",
                    drive_id="cloud-2",
                ),
                b"cloud",
                None,
                None,
            )
            if change.get("fileId") == "cloud-2"
            else (None, None, None, None)
        ),
        start_page_token=lambda: "new-token",
    )
    syncer.state = SimpleNamespace(
        delete_baseline_path=lambda *args, **kwargs: deleted.append("baseline"),
        upsert_baseline_entry=lambda entry: None,
        set_metadata=lambda key, value: None,
    )
    syncer.lock_path = "unused"
    syncer.lock_timeout = 1
    monkeypatch.setattr(
        "gdrive_sync.client.PairingLock",
        lambda *_args, **_kwargs: nullcontext(),
    )

    result = syncer._run_sync_incremental(
        token="token",
        baseline=baseline,
        conflict_policy="cloud-wins",
        dry_run=False,
    )

    assert deleted == []
    assert uploaded == []
    assert written == [("new-cloud.md", b"cloud")]
    assert result.created_files == ["new-cloud.md"]
