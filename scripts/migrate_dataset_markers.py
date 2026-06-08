"""Rename legacy dataset status markers locally or on Google Drive.

Dry-run is the default. Use --target drive to inspect the remote migration,
then add --apply to write the new Google Docs and remove legacy markers.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lib.env  # noqa: F401
from lib.active_dataset import ACTIVE_MARKER, ARCHIVED_MARKER, MARKER_TEXT
from lib.env import get_env_var

LEGACY_MARKERS = {
    "__active_dataset__": ACTIVE_MARKER,
    "__archived_dataset__": ARCHIVED_MARKER,
}


def build_plan(mirror_root: Path) -> dict:
    actions = []
    conflicts = []

    for legacy_name, current_name in LEGACY_MARKERS.items():
        for source in sorted(mirror_root.rglob(legacy_name)):
            if not source.is_file():
                continue
            destination = source.with_name(current_name)
            if destination.exists():
                conflicts.append(
                    {
                        "source": str(source),
                        "destination": str(destination),
                        "reason": "destination already exists",
                    }
                )
                continue
            actions.append(
                {
                    "source": str(source),
                    "destination": str(destination),
                    "status": "active" if legacy_name == "__active_dataset__" else "archived",
                }
            )

    return {
        "mirror_root": str(mirror_root),
        "actions": actions,
        "conflicts": conflicts,
        "counts": {
            "migrate": len(actions),
            "conflicts": len(conflicts),
        },
    }


def apply_plan(plan: dict) -> None:
    if plan["conflicts"]:
        raise ValueError("Marker migration has conflicts; refusing to apply")

    for action in plan["actions"]:
        source = Path(action["source"])
        destination = Path(action["destination"])
        destination.write_text(MARKER_TEXT, encoding="utf-8")
        source.unlink()


def build_drive_plan(mirror_root: Path, drive) -> dict:
    actions = []
    conflicts = []
    already_migrated = []

    for legacy_name, current_name in LEGACY_MARKERS.items():
        for source in sorted(mirror_root.rglob(current_name)):
            if not source.is_file():
                continue
            current_rel = source.relative_to(mirror_root).as_posix()
            legacy_rel = source.with_name(legacy_name).relative_to(mirror_root).as_posix()
            has_current = drive.exists(current_rel)
            has_legacy = drive.exists(legacy_rel)

            if has_legacy:
                actions.append(
                    {
                        "source": str(source),
                        "legacy": legacy_rel,
                        "destination": current_rel,
                        "replace_existing": has_current,
                    }
                )
            elif has_current:
                already_migrated.append(current_rel)
            else:
                conflicts.append(
                    {
                        "source": str(source),
                        "legacy": legacy_rel,
                        "destination": current_rel,
                        "reason": "neither legacy nor current marker exists on Drive",
                    }
                )

    return {
        "mirror_root": str(mirror_root),
        "actions": actions,
        "already_migrated": already_migrated,
        "conflicts": conflicts,
        "counts": {
            "migrate": len(actions),
            "already_migrated": len(already_migrated),
            "conflicts": len(conflicts),
        },
    }


def apply_drive_plan(plan: dict, drive) -> None:
    if plan["conflicts"]:
        raise ValueError("Drive marker migration has conflicts; refusing to apply")

    for action in plan["actions"]:
        source = Path(action["source"])
        destination = action["destination"]
        drive.write_bytes(destination, source.read_bytes())
        drive.set_mtime(destination, source.stat().st_mtime)
        drive.remove(action["legacy"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(get_env_var("STORAGE_MIRROR_PATH")),
        help="Local mirror root. Defaults to STORAGE_MIRROR_PATH.",
    )
    parser.add_argument(
        "--target",
        choices=("local", "drive"),
        default="local",
        help="Migration destination. Defaults to local.",
    )
    parser.add_argument("--apply", action="store_true", help="Apply the migration.")
    args = parser.parse_args()

    drive = None
    if args.target == "drive":
        from scripts.gdrive_sync import _build_sync_context

        _, drive = _build_sync_context(
            mirror_path=str(args.root),
            root_folder_id=None,
            credentials=None,
            token=None,
        )
        plan = build_drive_plan(args.root, drive)
    else:
        plan = build_plan(args.root)

    print(json.dumps(plan, indent=2))
    if args.apply:
        if args.target == "drive":
            apply_drive_plan(plan, drive)
            verification = build_drive_plan(args.root, drive)
            print(json.dumps({"verification": verification["counts"]}, indent=2))
            if verification["actions"] or verification["conflicts"]:
                return 1
        else:
            apply_plan(plan)
    return 1 if plan["conflicts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
