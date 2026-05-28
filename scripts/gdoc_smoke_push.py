"""
Manual smoke test: read a .md gdoc from Drive, modify the content, write it back,
and assert the file ID is unchanged (i.e. the update landed in place, no new file).

This proves the core property the migration is supposed to give us: editing a
.md via storage.write_text() updates the same gdoc, so future Google Docs UI
edits will keep happening on the same file ID forever.

Usage:
    # append a marker line
    python scripts/gdoc_smoke_push.py --root-folder-id 1A2B3C... --path foo.md \\
        --append "added by smoke push at 2026-05-28"

    # overwrite with the content of a local file
    python scripts/gdoc_smoke_push.py --root-folder-id 1A2B3C... --path foo.md \\
        --content-file /tmp/new.md
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lib.env  # noqa: F401  triggers .env load
from lib.storage_gdrive import GoogleDriveStorage, _GDOC_MIME


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root-folder-id", required=True)
    parser.add_argument("--path", required=True,
                        help="Relative path under the root (must end in .md).")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--append", help="Text to append (after a blank line).")
    mode.add_argument("--content-file", help="Local file whose content overwrites the gdoc.")
    parser.add_argument("--credentials",
                        default=os.environ.get("GDRIVE_CREDENTIALS")
                        or os.path.expanduser("~/.openclaw/gdrive-ops-credentials.json"))
    parser.add_argument("--token",
                        default=os.environ.get("GDRIVE_TOKEN")
                        or os.path.expanduser("~/.openclaw/gdrive-ops-token.json"))
    args = parser.parse_args()

    if not args.path.lower().endswith(".md"):
        print("ERROR: --path must end in .md (this harness tests the gdoc path).",
              file=sys.stderr)
        return 2

    storage = GoogleDriveStorage(
        credentials_path=args.credentials,
        token_path=args.token,
        root_folder_id=args.root_folder_id,
    )

    fid_before = storage._resolve(args.path)
    if fid_before is None:
        print(f"NOT FOUND: {args.path}", file=sys.stderr)
        return 1
    mime_before = storage._get_mime(args.path, fid_before)
    print(f"[before] id={fid_before}  mime={mime_before}")

    current = storage.read_text(args.path)
    print(f"[before] length={len(current)} chars")

    if args.append is not None:
        new_content = current.rstrip("\n") + "\n\n" + args.append + "\n"
    else:
        with open(args.content_file, "r", encoding="utf-8") as f:
            new_content = f.read()

    storage.write_text(args.path, new_content)

    # Drop caches so the next resolve hits Drive directly.
    storage.refresh()
    fid_after = storage._resolve(args.path)
    mime_after = storage._get_mime(args.path, fid_after) if fid_after else None
    print(f"[after]  id={fid_after}  mime={mime_after}")

    read_back = storage.read_text(args.path)
    print(f"[after]  length={len(read_back)} chars")

    ok_id = fid_after == fid_before
    ok_mime = mime_after == _GDOC_MIME
    if not ok_id:
        print(f"FAIL: file ID changed ({fid_before} -> {fid_after}). "
              f"Drive created a new file instead of updating in place.",
              file=sys.stderr)
    if not ok_mime:
        print(f"FAIL: mimeType after write is {mime_after!r}, expected {_GDOC_MIME}.",
              file=sys.stderr)
    if ok_id and ok_mime:
        print("OK: gdoc updated in place, file ID preserved.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
