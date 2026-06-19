import json
import sqlite3

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


def test_load_baseline_ignores_legacy_local_hash_cache_fields(tmp_path):
    state = SyncState(tmp_path / "state.sqlite3")
    legacy = {
        "path": "file.md",
        "type": "file",
        "sha256": "canonical-hash",
        "drive_id": "drive-1",
        "local_sha256": "cached-local-hash",
        "local_size": 42,
        "local_mtime_ns": 123,
    }
    with sqlite3.connect(state.path) as connection:
        connection.execute(
            "insert into baseline(path, entry_json) values(?, ?)",
            ("file.md", json.dumps(legacy)),
        )

    entry = state.load_baseline()["file.md"]
    assert entry.sha256 == "canonical-hash"
    assert entry.drive_id == "drive-1"
    assert not hasattr(entry, "local_sha256")
