"""Reorganize startup raw and parsed datasets into the standard folder layout.

Dry-run is the default. Use --apply only after reviewing the JSON manifest.
This script changes the local mirror only; push both migrated trees afterward:

    python scripts/gdrive_sync.py push storage/startups
    python scripts/gdrive_sync.py push storage/datasets2md/startups
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lib.env  # noqa: F401
from lib.active_dataset import MARKER_MTIME, MARKER_TEXT
from lib.env import get_env_var
from lib.startup_dossier import (
    STARTUP_DATASET_SUBDIRS,
    canonical_startup_slug,
)


@dataclass(frozen=True)
class Action:
    action: str
    source: str | None
    destination: str
    reason: str


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _migrated_relative(relative: Path) -> Path:
    parts = relative.parts
    if len(parts) < 2 or parts[0] != "datasets":
        return relative

    child_parts = parts[1:]
    if child_parts[0] in {"__active_dataset__", "__archived_dataset__"}:
        return relative
    if child_parts[0] in STARTUP_DATASET_SUBDIRS:
        return relative
    if len(child_parts) == 1:
        return Path("datasets", "snippets", child_parts[0])
    return Path("datasets", "data-room", *child_parts)


def _plan_tree(root: Path, *, create_active_marker: bool) -> tuple[list[Action], list[dict]]:
    actions: list[Action] = []
    conflicts: list[dict] = []
    startup_dirs = sorted(path for path in root.iterdir() if path.is_dir()) if root.exists() else []
    canonical_slugs = sorted({canonical_startup_slug(path.name) for path in startup_dirs})
    planned_destinations: dict[Path, Path] = {}

    for startup_dir in startup_dirs:
        canonical_slug = canonical_startup_slug(startup_dir.name)
        canonical_root = root / canonical_slug
        if startup_dir.name != canonical_slug:
            actions.append(
                Action(
                    "merge-startup",
                    str(startup_dir),
                    str(canonical_root),
                    "explicit startup alias",
                )
            )

        for source in sorted(path for path in startup_dir.rglob("*") if path.is_file()):
            relative = source.relative_to(startup_dir)
            migrated_relative = _migrated_relative(relative)
            destination = canonical_root / migrated_relative
            if source == destination:
                continue

            existing_source = planned_destinations.get(destination)
            if existing_source is not None:
                if _digest(existing_source) == _digest(source):
                    actions.append(
                        Action("deduplicate", str(source), str(destination), "identical planned content")
                    )
                else:
                    conflicts.append(
                        {
                            "destination": str(destination),
                            "sources": [str(existing_source), str(source)],
                            "reason": "multiple different source files map to one destination",
                        }
                    )
                continue

            if destination.exists() and destination != source:
                if _digest(destination) == _digest(source):
                    actions.append(
                        Action("deduplicate", str(source), str(destination), "identical existing content")
                    )
                else:
                    conflicts.append(
                        {
                            "destination": str(destination),
                            "sources": [str(destination), str(source)],
                            "reason": "destination already contains different content",
                        }
                    )
                continue

            planned_destinations[destination] = source
            actions.append(
                Action(
                    "move",
                    str(source),
                    str(destination),
                    "standard startup dataset layout",
                )
            )

    for slug in canonical_slugs:
        datasets_root = root / slug / "datasets"
        actions.append(Action("mkdir", None, str(datasets_root), "ensure dataset root"))
        for subdir in STARTUP_DATASET_SUBDIRS:
            actions.append(
                Action(
                    "mkdir",
                    None,
                    str(datasets_root / subdir),
                    "ensure standard dataset subfolder",
                )
            )
        if create_active_marker:
            marker = datasets_root / "__active_dataset__"
            actions.append(Action("activate", None, str(marker), "all migrated startups are active"))

    return actions, conflicts


def build_plan(mirror_root: Path) -> dict:
    trees = [
        ("raw", mirror_root / "storage/startups", True),
        ("parsed", mirror_root / "storage/datasets2md/startups", False),
    ]
    all_actions: list[Action] = []
    all_conflicts: list[dict] = []
    for tree_name, root, active in trees:
        actions, conflicts = _plan_tree(root, create_active_marker=active)
        all_actions.extend(actions)
        for conflict in conflicts:
            conflict["tree"] = tree_name
        all_conflicts.extend(conflicts)

    counts: dict[str, int] = {}
    for action in all_actions:
        counts[action.action] = counts.get(action.action, 0) + 1
    return {
        "mirror_root": str(mirror_root),
        "actions": [asdict(action) for action in all_actions],
        "conflicts": all_conflicts,
        "counts": counts,
    }


def apply_plan(plan: dict) -> None:
    if plan["conflicts"]:
        raise ValueError("Migration has conflicts; refusing to apply")

    for item in plan["actions"]:
        action = item["action"]
        source = Path(item["source"]) if item["source"] else None
        destination = Path(item["destination"])
        if action == "mkdir":
            destination.mkdir(parents=True, exist_ok=True)
        elif action == "activate":
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(MARKER_TEXT, encoding="utf-8")
            os.utime(destination, (MARKER_MTIME, MARKER_MTIME))
            archived = destination.parent / "__archived_dataset__"
            if archived.exists():
                archived.unlink()
        elif action == "move":
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
        elif action == "deduplicate":
            if source and source.exists():
                source.unlink()

    mirror_root = Path(plan["mirror_root"])
    for root in (
        mirror_root / "storage/startups",
        mirror_root / "storage/datasets2md/startups",
    ):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if path.is_dir():
                if path.name in {*STARTUP_DATASET_SUBDIRS, "datasets", "insights"}:
                    continue
                try:
                    path.rmdir()
                except OSError:
                    pass

    for item in plan["actions"]:
        if item["action"] != "merge-startup" or not item["source"]:
            continue
        source_root = Path(item["source"])
        if source_root.exists() and not any(path.is_file() for path in source_root.rglob("*")):
            shutil.rmtree(source_root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply the migration locally.")
    parser.add_argument(
        "--manifest",
        default="startup-dossier-migration.json",
        help="Path for the JSON migration manifest.",
    )
    args = parser.parse_args()

    mirror_root = Path(get_env_var("STORAGE_MIRROR_PATH"))
    plan = build_plan(mirror_root)
    manifest = Path(args.manifest)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(plan, indent=2), encoding="utf-8")

    print(json.dumps({"counts": plan["counts"], "conflicts": len(plan["conflicts"])}, indent=2))
    print(f"Manifest: {manifest.resolve()}")
    if args.apply:
        apply_plan(plan)
        print("Migration applied to local mirror.")
    else:
        print("Dry run only. No files changed.")
    return 1 if plan["conflicts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
