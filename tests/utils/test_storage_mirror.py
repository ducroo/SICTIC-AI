import pytest

from lib.storage import LocalStorage
from lib.storage_mirror import MirrorStorage


class FakeDrive:
    def __init__(self, *, fail_on_write: bool = False):
        self.fail_on_write = fail_on_write
        self.writes: list[tuple[str, bytes]] = []

    def write_bytes(self, rel: str, content: bytes) -> None:
        if self.fail_on_write:
            raise RuntimeError("drive unavailable")
        self.writes.append((rel, content))

    def exists(self, rel: str) -> bool:
        return False

    def is_dir(self, rel: str) -> bool:
        return False

    def list_with_mtime(self, rel: str, *, recursive: bool = False):
        return []

    def refresh(self, rel: str = "") -> None:
        return


def test_hybrid_markdown_write_uploads_after_local_write(tmp_path):
    local = LocalStorage(tmp_path)
    drive = FakeDrive()
    storage = MirrorStorage(local=local, drive=drive)

    storage.write_text("insights/startups/bewe/report.md", "# Report\n")

    assert (tmp_path / "insights/startups/bewe/report.md").read_text() == "# Report\n"
    assert drive.writes == [("insights/startups/bewe/report.md", b"# Report\n")]


def test_hybrid_cache_markdown_stays_local_only(tmp_path):
    local = LocalStorage(tmp_path)
    drive = FakeDrive()
    storage = MirrorStorage(local=local, drive=drive)

    storage.write_text("cache/datasets2md/startups/bewe/source.md", "# Cache\n")

    assert (tmp_path / "cache/datasets2md/startups/bewe/source.md").read_text() == "# Cache\n"
    assert drive.writes == []


def test_hybrid_non_markdown_write_stays_local_only(tmp_path):
    local = LocalStorage(tmp_path)
    drive = FakeDrive()
    storage = MirrorStorage(local=local, drive=drive)

    storage.write_bytes("datasets/startups/bewe/blob.pdf", b"pdf")

    assert (tmp_path / "datasets/startups/bewe/blob.pdf").read_bytes() == b"pdf"
    assert drive.writes == []


def test_hybrid_drive_upload_failure_keeps_local_file_and_raises(tmp_path):
    local = LocalStorage(tmp_path)
    drive = FakeDrive(fail_on_write=True)
    storage = MirrorStorage(local=local, drive=drive)

    with pytest.raises(RuntimeError, match="drive unavailable"):
        storage.write_text("insights/startups/bewe/report.md", "# Report\n")

    assert (tmp_path / "insights/startups/bewe/report.md").read_text() == "# Report\n"
