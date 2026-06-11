from gdrive_sync.drive import _local_rel_for_drive_item


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
