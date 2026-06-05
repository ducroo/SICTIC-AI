"""
Smoke-test every Storage protocol method against the LIVE backend selected by
GDRIVE_USE_API. With GDRIVE_USE_API=1 this exercises GoogleDriveStorage; without
it, LocalStorage(REPO_PATH). Same assertions either way.

If every method passes here, then every skill that uses these methods (which is
all of them, since the static scan confirmed no direct-FS) will be wired up
correctly under whichever mode you're in.

Run:
    venv/bin/python -m pytest tests/utils/test_storage_api_smoke.py -v
or as a script:
    venv/bin/python tests/utils/test_storage_api_smoke.py
"""

from __future__ import annotations

import os
import time

try:
    import pytest
except ImportError:
    pytest = None  # script-mode fallback below handles assertions inline

import lib.env  # triggers .env auto-load
from lib import storage as storage_module
from lib.storage import get_storage, reset_storage_singleton


PREFIX = f"_smoke/{int(time.time())}"


if pytest is not None:
    @pytest.fixture(scope="module")
    def s():
        reset_storage_singleton()
        inst = get_storage()
        print(f"\n[storage backend: {type(inst).__name__}, GDRIVE_USE_API={os.environ.get('GDRIVE_USE_API')!r}]")
        yield inst
        # cleanup
        try:
            inst.rmtree(PREFIX)
        except Exception as e:
            print(f"cleanup warning: {e}")


def test_write_then_read_text(s):
    rel = f"{PREFIX}/hello.txt"
    s.write_text(rel, "héllo wörld")
    assert s.read_text(rel) == "héllo wörld"


def test_write_then_read_md_gdoc_roundtrip(s):
    # .md paths are stored as native Google Docs on the gdrive backend; this
    # round-trip exercises the export/import path. Whitespace normalisation
    # tolerates gdoc's lossy reformatting (it strips trailing whitespace and
    # may add a final newline on export).
    rel = f"{PREFIX}/roundtrip.md"
    content = "# Title\n\nA short paragraph with **bold** and _italic_.\n"
    s.write_text(rel, content)
    got = s.read_text(rel)
    assert got.strip() == content.strip(), f"round-trip mismatch:\n--- wrote:\n{content!r}\n--- read:\n{got!r}"


def test_write_then_read_bytes(s):
    rel = f"{PREFIX}/blob.bin"
    payload = bytes(range(256))
    s.write_bytes(rel, payload)
    assert s.read_bytes(rel) == payload


def test_exists_and_is_dir(s):
    rel = f"{PREFIX}/probe.txt"
    s.write_text(rel, "x")
    assert s.exists(rel) is True
    assert s.exists(f"{PREFIX}/does-not-exist") is False
    assert s.is_dir(PREFIX) is True
    assert s.is_dir(rel) is False


def test_mkdir_idempotent(s):
    rel = f"{PREFIX}/sub/nested"
    s.mkdir(rel)
    s.mkdir(rel)  # second call should not raise
    assert s.is_dir(rel) is True


def test_list_non_recursive(s):
    base = f"{PREFIX}/lst"
    s.write_text(f"{base}/a.txt", "1")
    s.write_text(f"{base}/b.md", "2")
    s.write_text(f"{base}/c.json", "3")
    names = sorted(s.list(base))
    assert names == ["a.txt", "b.md", "c.json"]
    md_only = s.list(base, suffix=".md")
    assert md_only == ["b.md"]


def test_list_with_mtime_recursive(s):
    base = f"{PREFIX}/treewalk"
    s.write_text(f"{base}/top.md", "t")
    s.write_text(f"{base}/inner/deep.md", "d")
    items = s.list_with_mtime(base, recursive=True)
    names = sorted(n for n, _ in items)
    assert names == ["inner/deep.md", "top.md"]
    for _, mt in items:
        assert isinstance(mt, float) and mt > 0


def test_mtime(s):
    rel = f"{PREFIX}/mt.txt"
    s.write_text(rel, "v1")
    t1 = s.mtime(rel)
    assert isinstance(t1, float) and t1 > 0
    time.sleep(1.1)  # ensure mtime granularity
    s.write_text(rel, "v2")
    t2 = s.mtime(rel)
    assert t2 >= t1


def test_remove(s):
    rel = f"{PREFIX}/del.txt"
    s.write_text(rel, "bye")
    assert s.exists(rel)
    s.remove(rel)
    assert not s.exists(rel)


def test_rmtree(s):
    base = f"{PREFIX}/treedel"
    s.write_text(f"{base}/a.txt", "a")
    s.write_text(f"{base}/sub/b.txt", "b")
    assert s.exists(base)
    s.rmtree(base)
    assert not s.exists(base)


def test_refresh_does_not_raise(s):
    s.refresh()
    s.refresh(PREFIX)


def test_absolute_paths_are_rejected(s):
    """Storage API callers must pass relative paths, not local filesystem paths."""
    rel = f"{PREFIX}/normtest.txt"
    s.write_text(rel, "hi")

    mount = os.environ.get("REPO_PATH", "").rstrip("/")
    if mount:
        abs_path = f"{mount}/{rel}"
        with pytest.raises(ValueError):
            s.read_text(abs_path)

    with pytest.raises(ValueError):
        s.read_text("/etc/passwd")


if __name__ == "__main__":
    # Allow running as a plain script (without pytest) for quick checks.
    import sys
    reset_storage_singleton()
    inst = get_storage("repository_dir_mock")
    print(f"backend: {type(inst).__name__}, GDRIVE_USE_API={os.environ.get('GDRIVE_USE_API')!r}")
    tests = [(n, fn) for n, fn in globals().items() if n.startswith("test_") and callable(fn)]
    fails = 0
    for name, fn in tests:
        try:
            fn(inst)
            print(f"  PASS  {name}")
        except Exception as e:
            print(f"  FAIL  {name}: {type(e).__name__}: {e}")
            fails += 1
    # cleanup
    try:
        inst.rmtree(PREFIX)
    except Exception:
        pass
    sys.exit(fails)
