from skills.gdrive_sync.state import SyncState
from skills.gdrive_sync.types import SnapshotEntry


def test_baseline_drive_id_lookup_and_upsert(tmp_path):
    state = SyncState(tmp_path / "state.sqlite3")
    state.save_baseline(
        {
            "old.md": SnapshotEntry(
                path="old.md",
                type="file",
                sha256="old",
                drive_id="drive-1",
            )
        }
    )

    state.upsert_baseline_entry(
        SnapshotEntry(
            path="old.md",
            type="file",
            sha256="new",
            drive_id="drive-1",
        )
    )

    by_id = state.baseline_by_drive_id()
    assert by_id["drive-1"].path == "old.md"
    assert by_id["drive-1"].sha256 == "new"


def test_delete_baseline_path_can_remove_descendants(tmp_path):
    state = SyncState(tmp_path / "state.sqlite3")
    state.save_baseline(
        {
            "folder": SnapshotEntry(path="folder", type="folder", drive_id="folder-id"),
            "folder/a.md": SnapshotEntry(path="folder/a.md", type="file", drive_id="file-id"),
            "other.md": SnapshotEntry(path="other.md", type="file", drive_id="other-id"),
        }
    )

    state.delete_baseline_path("folder", include_descendants=True)

    assert set(state.load_baseline()) == {"other.md"}


def test_update_local_cache_preserves_canonical_baseline_hash(tmp_path):
    state = SyncState(tmp_path / "state.sqlite3")
    state.save_baseline(
        {
            "file.md": SnapshotEntry(
                path="file.md",
                type="file",
                sha256="cloud-hash",
                drive_id="drive-1",
            )
        }
    )

    state.update_local_cache(
        {
            "file.md": SnapshotEntry(
                path="file.md",
                type="file",
                sha256="local-hash",
                local_sha256="local-hash",
                local_size=42,
                local_mtime_ns=123,
            )
        }
    )

    entry = state.load_baseline()["file.md"]
    assert entry.sha256 == "cloud-hash"
    assert entry.local_sha256 == "local-hash"
    assert entry.local_size == 42
    assert entry.local_mtime_ns == 123


def test_upsert_baseline_preserves_local_cache(tmp_path):
    state = SyncState(tmp_path / "state.sqlite3")
    state.save_baseline(
        {
            "file.md": SnapshotEntry(
                path="file.md",
                type="file",
                sha256="old",
                local_sha256="local",
                local_size=42,
                local_mtime_ns=123,
            )
        }
    )

    state.upsert_baseline_entry(
        SnapshotEntry(path="file.md", type="file", sha256="new", drive_id="drive-1")
    )

    entry = state.load_baseline()["file.md"]
    assert entry.sha256 == "new"
    assert entry.local_sha256 == "local"
    assert entry.local_size == 42
    assert entry.local_mtime_ns == 123
