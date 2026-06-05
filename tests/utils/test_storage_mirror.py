import pytest

from lib.storage import LocalStorage
from lib.storage_mirror import MirrorStorage


class FakeDrive:
    def __init__(self, *, fail_on_write: bool = False, files=None):
        self.fail_on_write = fail_on_write
        self.files = files or {}
        self.mtimes = {path: mtime for path, (_, mtime) in self.files.items()}
        self.writes: list[tuple[str, bytes]] = []
        self.reads: list[str] = []
        self.list_calls: list[tuple[str, bool]] = []
        self.refreshes: list[str] = []

    def write_bytes(self, rel: str, content: bytes) -> None:
        if self.fail_on_write:
            raise RuntimeError("drive unavailable")
        self.writes.append((rel, content))
        self.files[rel] = (content, self.mtimes.get(rel, 0.0))

    def read_bytes(self, rel: str) -> bytes:
        self.reads.append(rel)
        return self.files[rel][0]

    def exists(self, rel: str) -> bool:
        if rel in {"", "."}:
            return True
        return rel in self.files or any(path.startswith(f"{rel}/") for path in self.files)

    def is_dir(self, rel: str) -> bool:
        if rel in {"", "."}:
            return True
        return any(path.startswith(f"{rel}/") for path in self.files)

    def list_with_mtime(self, rel: str, *, recursive: bool = False):
        self.list_calls.append((rel, recursive))
        prefix = f"{rel}/" if rel else ""
        out = []
        for path, (_, mtime) in self.files.items():
            if not path.startswith(prefix):
                continue
            name = path[len(prefix):]
            if not recursive and "/" in name:
                continue
            out.append((name, mtime))
        return out

    def mtime(self, rel: str):
        return self.mtimes.get(rel)

    def set_mtime(self, rel: str, timestamp: float) -> None:
        self.mtimes[rel] = timestamp
        if rel in self.files:
            self.files[rel] = (self.files[rel][0], timestamp)

    def refresh(self, rel: str = "") -> None:
        self.refreshes.append(rel)


def test_hybrid_markdown_write_uploads_after_local_write(tmp_path):
    local = LocalStorage(tmp_path)
    drive = FakeDrive()
    storage = MirrorStorage(local=local, drive=drive)

    storage.write_text("storage/startups/bewe/insights/report.md", "# Report\n")

    assert (tmp_path / "storage/startups/bewe/insights/report.md").read_text() == "# Report\n"
    assert drive.writes == [("storage/startups/bewe/insights/report.md", b"# Report\n")]


def test_hybrid_cache_markdown_stays_local_only(tmp_path):
    local = LocalStorage(tmp_path)
    drive = FakeDrive()
    storage = MirrorStorage(local=local, drive=drive)

    storage.write_text("cache/datasets2md/startups/bewe/source.md", "# Cache\n")

    assert (tmp_path / "cache/datasets2md/startups/bewe/source.md").read_text() == "# Cache\n"
    assert drive.writes == []


def test_hybrid_storage_datasets2md_markdown_uploads(tmp_path):
    local = LocalStorage(tmp_path)
    drive = FakeDrive()
    storage = MirrorStorage(local=local, drive=drive)

    storage.write_text("storage/datasets2md/startups/bewe/datasets/source.md", "# Parsed\n")

    assert (tmp_path / "storage/datasets2md/startups/bewe/datasets/source.md").read_text() == "# Parsed\n"
    assert drive.writes == [("storage/datasets2md/startups/bewe/datasets/source.md", b"# Parsed\n")]


def test_hybrid_non_markdown_write_stays_local_only(tmp_path):
    local = LocalStorage(tmp_path)
    drive = FakeDrive()
    storage = MirrorStorage(local=local, drive=drive)

    storage.write_bytes("storage/startups/bewe/datasets/blob.pdf", b"pdf")

    assert (tmp_path / "storage/startups/bewe/datasets/blob.pdf").read_bytes() == b"pdf"
    assert drive.writes == []


def test_hybrid_drive_upload_failure_keeps_local_file_and_raises(tmp_path):
    local = LocalStorage(tmp_path)
    drive = FakeDrive(fail_on_write=True)
    storage = MirrorStorage(local=local, drive=drive)

    with pytest.raises(RuntimeError, match="drive unavailable"):
        storage.write_text("storage/startups/bewe/insights/report.md", "# Report\n")

    assert (tmp_path / "storage/startups/bewe/insights/report.md").read_text() == "# Report\n"


def test_hybrid_list_recursively_pulls_drive_folder_and_preserves_mtime(tmp_path):
    local = LocalStorage(tmp_path)
    drive = FakeDrive(files={
        "storage/startups/bewe/insights/report.md": (b"# Remote\n", 200.0),
        "storage/startups/bewe/insights/nested/team.md": (b"# Team\n", 201.0),
    })
    storage = MirrorStorage(local=local, drive=drive)

    names = storage.list_with_mtime("storage/startups/bewe/insights", recursive=True)

    assert sorted(name for name, _ in names) == ["nested/team.md", "report.md"]
    assert (tmp_path / "storage/startups/bewe/insights/report.md").read_text() == "# Remote\n"
    assert local.mtime("storage/startups/bewe/insights/report.md") == 200.0
    assert drive.list_calls == [("storage/startups/bewe/insights", True)]


def test_hybrid_sync_prunes_local_files_missing_from_drive(tmp_path):
    local = LocalStorage(tmp_path)
    local.write_text("storage/startups/bewe/insights/stale.md", "# Stale\n")
    local.write_text("storage/startups/bewe/insights/keep.md", "# Old\n")
    local.set_mtime("storage/startups/bewe/insights/keep.md", 100.0)
    drive = FakeDrive(files={
        "storage/startups/bewe/insights/keep.md": (b"# Fresh\n", 200.0),
    })
    storage = MirrorStorage(local=local, drive=drive)

    assert storage.exists("storage/startups/bewe/insights")

    assert not local.exists("storage/startups/bewe/insights/stale.md")
    assert local.read_text("storage/startups/bewe/insights/keep.md") == "# Fresh\n"
    assert local.mtime("storage/startups/bewe/insights/keep.md") == 200.0


def test_hybrid_syncs_a_drive_file_without_listing_parent_folder(tmp_path):
    local = LocalStorage(tmp_path)
    drive = FakeDrive(files={
        "storage/startups/bewe/insights/other.md": (b"# Other\n", 201.0),
        "storage/startups/bewe/insights/report.md": (b"# Remote\n", 200.0),
    })
    storage = MirrorStorage(local=local, drive=drive)

    assert storage.exists("storage/startups/bewe/insights/report.md")
    assert storage.exists("storage/startups/bewe/insights/report.md")

    assert drive.list_calls == []
    assert drive.reads == ["storage/startups/bewe/insights/report.md"]
    assert local.read_text("storage/startups/bewe/insights/report.md") == "# Remote\n"
    assert not local.exists("storage/startups/bewe/insights/other.md")


def test_hybrid_syncs_a_drive_folder_only_once_per_process(tmp_path):
    local = LocalStorage(tmp_path)
    drive = FakeDrive(files={
        "storage/startups/bewe/insights/report.md": (b"# Remote\n", 200.0),
    })
    storage = MirrorStorage(local=local, drive=drive)

    assert storage.exists("storage/startups/bewe/insights")
    assert storage.exists("storage/startups/bewe/insights")

    assert drive.list_calls == [("storage/startups/bewe/insights", True)]


def test_hybrid_exists_on_drive_folder_syncs_that_folder_not_parent(tmp_path):
    local = LocalStorage(tmp_path)
    drive = FakeDrive(files={
        "storage/startups/bewe/datasets/source.pdf": (b"pdf", 200.0),
    })
    storage = MirrorStorage(local=local, drive=drive)

    assert storage.exists("storage/startups/bewe/datasets")

    assert drive.list_calls == [("storage/startups/bewe/datasets", True)]
    assert local.exists("storage/startups/bewe/datasets/source.pdf")
