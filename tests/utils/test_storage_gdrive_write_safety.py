import threading

import pytest

from lib.storage_gdrive import GoogleDriveStorage, _sanitize_markdown_upload


class _FakeListRequest:
    def __init__(self, files):
        self._files = files

    def execute(self):
        return {"files": self._files}


class _FakeExecuteRequest:
    def __init__(self, result=None, callback=None):
        self._result = result or {}
        self._callback = callback
        self.num_retries = None

    def execute(self, num_retries=0):
        self.num_retries = num_retries
        if self._callback:
            self._callback()
        return self._result


class _FakeFiles:
    def __init__(self, files):
        self._files = files
        self.created = []
        self.updated = []
        self.deleted = []
        self.requests = []

    def list(self, **kwargs):
        return _FakeListRequest(self._files)

    def create(self, **kwargs):
        self.created.append(kwargs)
        request = _FakeExecuteRequest({"id": "created-gdoc"})
        self.requests.append(request)
        return request

    def update(self, **kwargs):
        self.updated.append(kwargs)
        request = _FakeExecuteRequest({"id": kwargs["fileId"]})
        self.requests.append(request)
        return request

    def delete(self, **kwargs):
        self.deleted.append(kwargs["fileId"])
        return _FakeExecuteRequest()


class _FakeService:
    def __init__(self, files):
        self._files = _FakeFiles(files)

    def files(self):
        return self._files


def _storage_with_files(files):
    storage = GoogleDriveStorage.__new__(GoogleDriveStorage)
    storage._service_lock = threading.Lock()
    storage._path_to_id = {"": "root", "insights": "parent"}
    storage._path_to_mime = {"": "application/vnd.google-apps.folder"}
    storage._dir_children = {}
    storage._root_resolved = True
    storage.root_folder_id = "root"
    storage._service = _FakeService(files)
    storage._ensure_service = lambda: storage._service
    return storage


def test_gdrive_write_resolution_rejects_duplicate_same_name_files():
    storage = _storage_with_files([
        {"id": "a", "name": "report.md", "mimeType": "application/vnd.google-apps.document"},
        {"id": "b", "name": "report.md", "mimeType": "application/vnd.google-apps.document"},
    ])

    with pytest.raises(RuntimeError, match="ambiguous Google Drive path"):
        storage._resolve_unique_child_for_write("parent", "insights/report.md", "report.md")


def test_markdown_upload_sanitizer_removes_disallowed_ascii_controls():
    content = b"a\x00b\x08c\tday\nend\rnext\x0bmore\x13\x14last\x1f\x7f"

    assert _sanitize_markdown_upload(content) == b"abc\tday\nend\rnextmorelast"


def test_markdown_upload_sanitizer_preserves_utf8_bytes():
    content = "Markdown with non-breaking\u00a0space and umlaut \u00fc.".encode()

    assert _sanitize_markdown_upload(content) == content


def test_gdrive_write_resolution_accepts_one_existing_file():
    storage = _storage_with_files([
        {"id": "a", "name": "report.md", "mimeType": "application/vnd.google-apps.document"},
    ])

    result = storage._resolve_unique_child_for_write("parent", "insights/report.md", "report.md")

    assert result["id"] == "a"
    assert storage._path_to_id["insights/report.md"] == "a"
    assert storage._path_to_mime["insights/report.md"] == "application/vnd.google-apps.document"


def test_gdrive_md_resolution_prefers_gdoc_over_legacy_markdown():
    storage = _storage_with_files([
        {"id": "legacy", "name": "report.md", "mimeType": "text/markdown"},
        {"id": "gdoc", "name": "report.md", "mimeType": "application/vnd.google-apps.document"},
    ])

    assert storage._resolve("insights/report.md") == "gdoc"
    assert storage._path_to_mime["insights/report.md"] == "application/vnd.google-apps.document"


def test_gdrive_md_write_converts_legacy_markdown_and_deletes_it():
    storage = _storage_with_files([
        {"id": "legacy", "name": "report.md", "mimeType": "text/markdown"},
    ])
    storage._resolve_root_folder = lambda: None
    storage.mkdir = lambda *args, **kwargs: None
    storage._resolve_or_raise = lambda rel: "parent" if rel == "insights" else rel

    storage.write_bytes("insights/report.md", b"# Report\n")

    files = storage._service.files()
    assert len(files.created) == 1
    assert files.created[0]["body"]["mimeType"] == "application/vnd.google-apps.document"
    assert files.requests[0].num_retries == 5
    assert files.deleted == ["legacy"]


def test_gdrive_md_write_updates_gdoc_and_deletes_legacy_duplicate():
    storage = _storage_with_files([
        {"id": "gdoc", "name": "report.md", "mimeType": "application/vnd.google-apps.document"},
        {"id": "legacy", "name": "report.md", "mimeType": "text/markdown"},
    ])
    storage._resolve_root_folder = lambda: None
    storage.mkdir = lambda *args, **kwargs: None
    storage._resolve_or_raise = lambda rel: "parent" if rel == "insights" else rel

    storage.write_bytes("insights/report.md", b"# Report\n")

    files = storage._service.files()
    assert len(files.updated) == 1
    assert files.updated[0]["fileId"] == "gdoc"
    assert files.requests[0].num_retries == 5
    assert files.created == []
    assert files.deleted == ["legacy"]
