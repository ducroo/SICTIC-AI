from pathlib import Path

from lib.active_dataset import MARKER_TEXT
from scripts.migrate_dataset_markers import (
    apply_drive_plan,
    apply_plan,
    build_drive_plan,
    build_plan,
)


class _FakeDrive:
    def __init__(self, files):
        self.files = dict(files)
        self.mtimes = {}

    def exists(self, rel):
        return rel in self.files

    def write_bytes(self, rel, content):
        self.files[rel] = content

    def set_mtime(self, rel, timestamp):
        self.mtimes[rel] = timestamp

    def remove(self, rel):
        self.files.pop(rel, None)


def test_migrates_legacy_markers_with_current_names_and_content(tmp_path):
    mirror = tmp_path / "mirror"
    active = mirror / "storage/startups/example/datasets/__active_dataset__"
    archived = mirror / "storage/community/example/datasets/__archived_dataset__"
    active.parent.mkdir(parents=True)
    archived.parent.mkdir(parents=True)
    active.write_text("legacy", encoding="utf-8")
    archived.write_text("legacy", encoding="utf-8")

    plan = build_plan(mirror)

    assert plan["counts"] == {"migrate": 2, "conflicts": 0}
    apply_plan(plan)
    assert not active.exists()
    assert not archived.exists()
    assert active.with_name("__active_dataset__.md").read_text() == MARKER_TEXT
    assert archived.with_name("__archived_dataset__.md").read_text() == MARKER_TEXT


def test_reports_conflict_when_current_marker_exists(tmp_path):
    mirror = tmp_path / "mirror"
    legacy = mirror / "storage/startups/example/datasets/__active_dataset__"
    current = legacy.with_name("__active_dataset__.md")
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy", encoding="utf-8")
    current.write_text("current", encoding="utf-8")

    plan = build_plan(mirror)

    assert plan["counts"] == {"migrate": 0, "conflicts": 1}


def test_drive_migration_writes_current_marker_before_removing_legacy(tmp_path):
    mirror = tmp_path / "mirror"
    current = mirror / "storage/startups/example/datasets/__active_dataset__.md"
    current.parent.mkdir(parents=True)
    current.write_text(MARKER_TEXT, encoding="utf-8")
    legacy_rel = "storage/startups/example/datasets/__active_dataset__"
    current_rel = f"{legacy_rel}.md"
    drive = _FakeDrive({legacy_rel: b"legacy"})

    plan = build_drive_plan(mirror, drive)

    assert plan["counts"] == {
        "migrate": 1,
        "already_migrated": 0,
        "conflicts": 0,
    }
    apply_drive_plan(plan, drive)
    assert legacy_rel not in drive.files
    assert drive.files[current_rel] == MARKER_TEXT.encode()
    assert current_rel in drive.mtimes


def test_drive_migration_treats_current_only_marker_as_complete(tmp_path):
    mirror = tmp_path / "mirror"
    current = mirror / "storage/startups/example/datasets/__active_dataset__.md"
    current.parent.mkdir(parents=True)
    current.write_text(MARKER_TEXT, encoding="utf-8")
    current_rel = "storage/startups/example/datasets/__active_dataset__.md"
    drive = _FakeDrive({current_rel: MARKER_TEXT.encode()})

    plan = build_drive_plan(mirror, drive)

    assert plan["counts"] == {
        "migrate": 0,
        "already_migrated": 1,
        "conflicts": 0,
    }


def test_drive_migration_refuses_missing_remote_marker(tmp_path):
    mirror = tmp_path / "mirror"
    current = mirror / "storage/startups/example/datasets/__active_dataset__.md"
    current.parent.mkdir(parents=True)
    current.write_text(MARKER_TEXT, encoding="utf-8")

    plan = build_drive_plan(mirror, _FakeDrive({}))

    assert plan["counts"] == {
        "migrate": 0,
        "already_migrated": 0,
        "conflicts": 1,
    }
