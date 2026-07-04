import os

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


def test_local_scan_always_rehashes_files(tmp_path, monkeypatch):
    path = tmp_path / "visible.md"
    path.write_text("unchanged")
    tree = LocalTree(tmp_path)
    tree.scan()
    calls = []

    monkeypatch.setattr(
        "gdrive_sync.local.sha256_file",
        lambda hashed_path: calls.append(hashed_path) or "fresh-hash",
    )

    current = tree.scan()

    assert current["visible.md"].sha256 == "fresh-hash"
    assert calls == [path]


def test_local_scan_detects_change_with_preserved_size_and_timestamp(tmp_path):
    path = tmp_path / "visible.md"
    path.write_text("old")
    tree = LocalTree(tmp_path)
    baseline = tree.scan()
    previous_stat = path.stat()
    path.write_text("new")
    os.utime(
        path,
        ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns),
    )

    current = tree.scan()

    assert current["visible.md"].size == baseline["visible.md"].size
    assert path.stat().st_mtime_ns == previous_stat.st_mtime_ns
    assert current["visible.md"].sha256 != baseline["visible.md"].sha256
