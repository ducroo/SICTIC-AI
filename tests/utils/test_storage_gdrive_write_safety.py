import threading

import pytest

from lib.storage_gdrive import GoogleDriveStorage


class _FakeListRequest:
    def __init__(self, files):
        self._files = files

    def execute(self):
        return {"files": self._files}


class _FakeFiles:
    def __init__(self, files):
        self._files = files

    def list(self, **kwargs):
        return _FakeListRequest(self._files)


class _FakeService:
    def __init__(self, files):
        self._files = _FakeFiles(files)

    def files(self):
        return self._files


def _storage_with_files(files):
    storage = GoogleDriveStorage.__new__(GoogleDriveStorage)
    storage._service_lock = threading.Lock()
    storage._path_to_id = {}
    storage._path_to_mime = {}
    storage._ensure_service = lambda: _FakeService(files)
    return storage


def test_gdrive_write_resolution_rejects_duplicate_same_name_files():
    storage = _storage_with_files([
        {"id": "a", "name": "report.md", "mimeType": "application/vnd.google-apps.document"},
        {"id": "b", "name": "report.md", "mimeType": "application/vnd.google-apps.document"},
    ])

    with pytest.raises(RuntimeError, match="ambiguous Google Drive path"):
        storage._resolve_unique_child_for_write("parent", "insights/report.md", "report.md")


def test_gdrive_write_resolution_accepts_one_existing_file():
    storage = _storage_with_files([
        {"id": "a", "name": "report.md", "mimeType": "application/vnd.google-apps.document"},
    ])

    result = storage._resolve_unique_child_for_write("parent", "insights/report.md", "report.md")

    assert result["id"] == "a"
    assert storage._path_to_id["insights/report.md"] == "a"
    assert storage._path_to_mime["insights/report.md"] == "application/vnd.google-apps.document"
