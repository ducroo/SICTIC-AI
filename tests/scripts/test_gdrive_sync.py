import pytest

from scripts import gdrive_sync


class _FakeStore:
    def __init__(self, files=None):
        self.files = files or {}
        self.mtimes = {path: mtime for path, (_, mtime) in self.files.items()}
        self.reads = []
        self.writes = []
        self.removed = []
        self.set_mtimes = []

    def exists(self, rel):
        return rel in self.files

    def mtime(self, rel):
        return self.mtimes.get(rel)

    def read_bytes(self, rel):
        self.reads.append(rel)
        return self.files[rel][0]

    def write_bytes(self, rel, content):
        self.writes.append((rel, content))
        self.files[rel] = (content, self.mtimes.get(rel, 0.0))

    def set_mtime(self, rel, timestamp):
        self.set_mtimes.append((rel, timestamp))
        content = self.files[rel][0]
        self.files[rel] = (content, timestamp)
        self.mtimes[rel] = timestamp

    def remove(self, rel):
        self.removed.append(rel)
        self.files.pop(rel, None)
        self.mtimes.pop(rel, None)


def test_clean_rel_rejects_absolute_paths():
    with pytest.raises(ValueError):
        gdrive_sync._clean_rel("/insights")


def test_clean_rel_rejects_parent_segments():
    with pytest.raises(ValueError):
        gdrive_sync._clean_rel("../insights")


def test_pull_file_skips_when_mtime_matches():
    drive = _FakeStore({"insights/a.md": (b"remote", 100.0)})
    mirror = _FakeStore({"insights/a.md": (b"local", 100.0)})

    changed = gdrive_sync._pull_file(drive, mirror, "insights/a.md", 100.0)

    assert changed is False
    assert drive.reads == []
    assert mirror.writes == []


def test_pull_file_copies_and_preserves_drive_mtime_when_changed():
    drive = _FakeStore({"insights/a.md": (b"remote", 200.0)})
    mirror = _FakeStore({"insights/a.md": (b"local", 100.0)})

    changed = gdrive_sync._pull_file(drive, mirror, "insights/a.md", 200.0)

    assert changed is True
    assert mirror.files["insights/a.md"] == (b"remote", 200.0)


def test_push_file_skips_when_mtime_matches():
    mirror = _FakeStore({"insights/a.md": (b"local", 100.0)})
    drive = _FakeStore({"insights/a.md": (b"remote", 100.0)})

    changed = gdrive_sync._push_file(mirror, drive, "insights/a.md", 100.0)

    assert changed is False
    assert mirror.reads == []
    assert drive.writes == []


def test_push_file_copies_and_preserves_local_mtime_when_changed():
    mirror = _FakeStore({"insights/a.md": (b"local", 200.0)})
    drive = _FakeStore({"insights/a.md": (b"remote", 100.0)})

    changed = gdrive_sync._push_file(mirror, drive, "insights/a.md", 200.0)

    assert changed is True
    assert drive.files["insights/a.md"] == (b"local", 200.0)
