"""
Manual smoke test: pull a .md file from a Drive test folder and print its content.

Exercises lib/storage_gdrive.py's gdoc-export read path. Useful after running
scripts/convert_md_to_gdoc.py to verify the .md you uploaded is now a gdoc and
that exporting it back to markdown works.

Usage:
    python scripts/gdoc_smoke_pull.py --root-folder-id 1A2B3C... --path foo.md
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
    parser.add_argument("--root-folder-id", required=True,
                        help="Drive folder ID to use as storage root.")
    parser.add_argument("--path", required=True,
                        help="Relative path under the root (e.g. 'foo.md').")
    parser.add_argument("--output",
                        help="Local file path to write the markdown content to. "
                             "If omitted, content is printed to stdout.")
    parser.add_argument("--credentials",
                        default=os.environ.get("GDRIVE_CREDENTIALS")
                        or os.path.expanduser("~/.openclaw/gdrive-ops-credentials.json"))
    parser.add_argument("--token",
                        default=os.environ.get("GDRIVE_TOKEN")
                        or os.path.expanduser("~/.openclaw/gdrive-ops-token.json"))
    args = parser.parse_args()

    storage = GoogleDriveStorage(
        credentials_path=args.credentials,
        token_path=args.token,
        root_folder_id=args.root_folder_id,
    )

    fid = storage._resolve(args.path)
    if fid is None:
        print(f"NOT FOUND: {args.path}", file=sys.stderr)
        return 1
    mime = storage._get_mime(args.path, fid)

    content = storage.read_text(args.path)

    print(f"--- file ID: {fid}", file=sys.stderr)
    print(f"--- mimeType: {mime}  (expected: {_GDOC_MIME})", file=sys.stderr)
    print(f"--- length: {len(content)} chars", file=sys.stderr)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"--- wrote: {args.output}", file=sys.stderr)
    else:
        print("--- content:", file=sys.stderr)
        print(content)
    return 0


if __name__ == "__main__":
    sys.exit(main())
