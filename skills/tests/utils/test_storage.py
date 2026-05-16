import time

import pytest

from skills.utils.storage import (
    LocalStorage,
    MockStorage,
    RoutedStorage,
    _validate_rel,
)


@pytest.fixture
def store(tmp_path):
    return LocalStorage(tmp_path)


def test_validate_rejects_absolute():
    with pytest.raises(ValueError):
        _validate_rel("/etc/passwd")


def test_validate_rejects_parent_traversal():
    with pytest.raises(ValueError):
        _validate_rel("../escape")
    with pytest.raises(ValueError):
        _validate_rel("foo/../escape")


def test_write_then_read_text(store):
    store.write_text("insights/widgetco/foo.md", "hello")
    assert store.read_text("insights/widgetco/foo.md") == "hello"


def test_write_creates_parent_dirs(store):
    store.write_text("a/b/c/d.md", "x")
    assert store.exists("a/b/c/d.md")
    assert store.is_dir("a/b/c")


def test_write_then_read_bytes(store):
    payload = b"\x00\x01\x02"
    store.write_bytes("blob.bin", payload)
    assert store.read_bytes("blob.bin") == payload


def test_exists_false_for_missing(store):
    assert store.exists("nope.md") is False


def test_list_filters_by_suffix(store):
    store.write_text("d/a.json", "1")
    store.write_text("d/b.md", "2")
    store.write_text("d/c.json", "3")
    assert store.list("d", suffix=".json") == ["a.json", "c.json"]
    assert store.list("d") == ["a.json", "b.md", "c.json"]


def test_list_empty_for_missing_dir(store):
    assert store.list("nope") == []


def test_list_with_mtime_nonrecursive(store):
    store.write_text("d/a.md", "1")
    store.write_text("d/sub/b.md", "2")
    entries = store.list_with_mtime("d", recursive=False)
    names = sorted(n for n, _ in entries)
    assert names == ["a.md"]


def test_list_with_mtime_recursive(store):
    store.write_text("d/a.md", "1")
    store.write_text("d/sub/b.md", "2")
    entries = store.list_with_mtime("d", recursive=True)
    names = sorted(n for n, _ in entries)
    assert names == ["a.md", "sub/b.md"]


def test_mtime_returns_none_for_missing(store):
    assert store.mtime("nope.md") is None


def test_mtime_returns_float(store):
    before = time.time() - 1
    store.write_text("a.md", "x")
    mt = store.mtime("a.md")
    assert isinstance(mt, float)
    assert mt >= before


def test_remove_is_idempotent(store):
    store.write_text("a.md", "x")
    store.remove("a.md")
    store.remove("a.md")  # should not raise
    assert not store.exists("a.md")


def test_rmtree_removes_dir(store):
    store.write_text("d/a.md", "1")
    store.write_text("d/sub/b.md", "2")
    store.rmtree("d")
    assert not store.exists("d")


def test_rmtree_missing_dir_is_noop(store):
    store.rmtree("nope")  # should not raise


def test_mkdir(store):
    store.mkdir("a/b/c")
    assert store.is_dir("a/b/c")


def test_mock_storage_is_local(tmp_path):
    m = MockStorage(tmp_path)
    m.write_text("a.md", "x")
    assert m.read_text("a.md") == "x"


# ---------- RoutedStorage ----------


def test_routed_sends_caches_to_cache_storage(tmp_path):
    drive = LocalStorage(tmp_path / "drive")
    cache = LocalStorage(tmp_path / "cache")
    routed = RoutedStorage(drive=drive, cache=cache)

    routed.write_text("datasets_parsed/widgetco/foo.md", "parsed")
    routed.write_text("insights/widgetco/dd.md", "insight")
    routed.write_text("datasets/widgetco/source.pdf", "src")

    # cache subtree went to cache
    assert (tmp_path / "cache" / "datasets_parsed" / "widgetco" / "foo.md").exists()
    # everything else went to drive
    assert (tmp_path / "drive" / "insights" / "widgetco" / "dd.md").exists()
    assert (tmp_path / "drive" / "datasets" / "widgetco" / "source.pdf").exists()


def test_routed_reads_from_correct_backend(tmp_path):
    drive = LocalStorage(tmp_path / "drive")
    cache = LocalStorage(tmp_path / "cache")
    routed = RoutedStorage(drive=drive, cache=cache)

    routed.write_text("datasets_parsed/a.md", "from-cache")
    routed.write_text("insights/b.md", "from-drive")

    assert routed.read_text("datasets_parsed/a.md") == "from-cache"
    assert routed.read_text("insights/b.md") == "from-drive"
