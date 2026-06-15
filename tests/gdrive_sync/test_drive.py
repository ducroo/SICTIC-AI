from types import SimpleNamespace

import pytest

from skills.gdrive_sync.drive import DriveTree, GDOC_SAFE_MAX_CHARACTERS, _local_rel_for_drive_item


def test_google_doc_without_md_suffix_maps_to_markdown_file():
    rel = _local_rel_for_drive_item(
        "registry",
        "Ignore me - test",
        "application/vnd.google-apps.document",
    )

    assert rel == "registry/Ignore me - test.md"


def test_google_doc_with_md_suffix_keeps_name():
    rel = _local_rel_for_drive_item(
        "registry",
        "notes.md",
        "application/vnd.google-apps.document",
    )

    assert rel == "registry/notes.md"


def test_binary_file_keeps_name():
    rel = _local_rel_for_drive_item("registry", "data.json", "application/json")

    assert rel == "registry/data.json"


def test_markdown_over_google_doc_safety_limit_is_rejected_before_upload():
    tree = DriveTree.__new__(DriveTree)
    uploads = []
    tree.storage = type(
        "Storage",
        (),
        {"write_bytes": lambda self, rel, content: uploads.append((rel, content))},
    )()

    with pytest.raises(ValueError, match="Google Doc upload safety limit"):
        tree.write_bytes("large.md", b"x" * (GDOC_SAFE_MAX_CHARACTERS + 1))

    assert uploads == []


def test_non_markdown_over_google_doc_safety_limit_still_uploads():
    tree = DriveTree.__new__(DriveTree)
    uploads = []
    tree.storage = type(
        "Storage",
        (),
        {"write_bytes": lambda self, rel, content: uploads.append((rel, content))},
    )()
    content = b"x" * (GDOC_SAFE_MAX_CHARACTERS + 1)

    tree.write_bytes("large.pdf", content)

    assert uploads == [("large.pdf", content)]


def test_change_entry_can_be_inspected_without_downloading_content():
    tree = DriveTree.__new__(DriveTree)
    tree.exclude = []
    tree.storage = SimpleNamespace(
        _path_to_id={},
        _path_to_mime={},
        read_bytes=lambda _path: pytest.fail("content should not be read"),
    )
    tree._path_for_file = lambda _meta: "folder/file.md"

    entry, content, warning, failure = tree.entry_for_change(
        {
            "fileId": "file-id",
            "file": {
                "id": "file-id",
                "name": "file.md",
                "mimeType": "application/vnd.google-apps.document",
                "size": "123",
            },
        },
        include_content=False,
    )

    assert entry is not None
    assert entry.path == "folder/file.md"
    assert entry.size == 123
    assert entry.sha256 is None
    assert content is None
    assert warning is None
    assert failure is None
