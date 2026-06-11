from gdrive_sync.local import LocalTree


def test_local_scan_ignores_hidden_files_dirs_and_exclusions(tmp_path):
    (tmp_path / ".hidden").write_text("no")
    (tmp_path / ".dir").mkdir()
    (tmp_path / ".dir" / "x.md").write_text("no")
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "x.tmp").write_text("no")
    (tmp_path / "visible.md").write_text("yes")

    tree = LocalTree(tmp_path, exclude=["cache/**"])

    assert set(tree.scan()) == {"visible.md"}
