import os
import threading

import pytest

from skills.gdrive_sync.local import LocalTree


def test_local_scan_ignores_hidden_files_dirs_and_exclusions(tmp_path):
    (tmp_path / ".hidden").write_text("no")
    (tmp_path / ".dir").mkdir()
    (tmp_path / ".dir" / "x.md").write_text("no")
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "x.tmp").write_text("no")
    (tmp_path / "visible.md").write_text("yes")

    tree = LocalTree(tmp_path, exclude=["cache/**"])

    assert set(tree.scan()) == {"visible.md"}


def test_local_scan_reuses_hash_when_size_and_timestamp_match(tmp_path, monkeypatch):
    path = tmp_path / "visible.md"
    path.write_text("unchanged")
    tree = LocalTree(tmp_path)
    baseline = tree.scan()

    monkeypatch.setattr(
        "skills.gdrive_sync.local.sha256_file",
        lambda _path: pytest.fail("unchanged file should not be rehashed"),
    )

    current = tree.scan(baseline)

    assert current["visible.md"].sha256 == baseline["visible.md"].sha256


def test_local_scan_rehashes_when_size_changes(tmp_path, monkeypatch):
    path = tmp_path / "visible.md"
    path.write_text("old")
    tree = LocalTree(tmp_path)
    baseline = tree.scan()
    path.write_text("different size")
    calls = []

    monkeypatch.setattr(
        "skills.gdrive_sync.local.sha256_file",
        lambda changed_path: calls.append(changed_path) or "new-hash",
    )

    current = tree.scan(baseline)

    assert current["visible.md"].sha256 == "new-hash"
    assert calls == [path]


def test_local_scan_rehashes_when_timestamp_changes(tmp_path, monkeypatch):
    path = tmp_path / "visible.md"
    path.write_text("first")
    tree = LocalTree(tmp_path)
    baseline = tree.scan()
    previous_stat = path.stat()
    path.write_text("other")
    os.utime(
        path,
        ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns + 1_000_000),
    )
    calls = []

    monkeypatch.setattr(
        "skills.gdrive_sync.local.sha256_file",
        lambda changed_path: calls.append(changed_path) or "new-hash",
    )

    current = tree.scan(baseline)

    assert current["visible.md"].sha256 == "new-hash"
    assert calls == [path]


def test_local_scan_hashes_candidates_in_parallel(tmp_path, monkeypatch):
    paths = [tmp_path / "a.md", tmp_path / "b.md"]
    for path in paths:
        path.write_text(path.name)
    barrier = threading.Barrier(2, timeout=2)
    thread_ids = set()

    def hash_in_parallel(path):
        thread_ids.add(threading.get_ident())
        barrier.wait()
        return path.name

    monkeypatch.setattr("skills.gdrive_sync.local.sha256_file", hash_in_parallel)

    current = LocalTree(tmp_path).scan()

    assert current["a.md"].sha256 == "a.md"
    assert current["b.md"].sha256 == "b.md"
    assert len(thread_ids) == 2
