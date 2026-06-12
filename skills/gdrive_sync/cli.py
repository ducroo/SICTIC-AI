from __future__ import annotations

import argparse
import json
import logging
import sys

from .client import GDriveSync
from .types import GDriveSyncError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m skills.gdrive_sync",
        description="Synchronize LOCAL_STORAGE_PATH with the CLOUD_STORAGE_PATH Google Drive root.",
    )
    parser.add_argument("operation", choices=["push", "pull", "sync"])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report planned changes without modifying local files, Drive, or the successful baseline.",
    )
    conflict_group = parser.add_mutually_exclusive_group()
    conflict_group.add_argument(
        "--local-wins",
        dest="conflict_policy",
        action="store_const",
        const="local-wins",
        help="For sync conflicts, keep the local version as canonical.",
    )
    conflict_group.add_argument(
        "--cloud-wins",
        dest="conflict_policy",
        action="store_const",
        const="cloud-wins",
        help="For sync conflicts, keep the cloud version as canonical.",
    )
    parser.add_argument("--local-root")
    parser.add_argument("--cloud-root")
    parser.add_argument("--credentials-path")
    parser.add_argument("--token-path")
    parser.add_argument("--state-dir")
    parser.add_argument("--log-dir")
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--lock-timeout", type=float, default=1800)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", action="store_true", help="Emit OperationResult as JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.operation == "sync" and args.conflict_policy is None:
        parser.error("sync requires either --local-wins or --cloud-wins")
    if args.operation != "sync" and args.conflict_policy is not None:
        parser.error("--local-wins and --cloud-wins are only valid with sync")
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s")
    try:
        syncer = GDriveSync(
            local_root=args.local_root,
            gdrive_root=args.cloud_root,
            credentials_path=args.credentials_path,
            token_path=args.token_path,
            exclude=args.exclude,
            lock_timeout=args.lock_timeout,
            state_dir=args.state_dir,
            log_dir=args.log_dir,
            verbose=args.verbose,
        )
        if args.operation == "push":
            result = syncer.push(dry_run=args.dry_run)
        elif args.operation == "pull":
            result = syncer.pull(dry_run=args.dry_run)
        else:
            result = syncer.sync(conflict_policy=args.conflict_policy, dry_run=args.dry_run)
    except (GDriveSyncError, ValueError) as exc:
        result = exc.partial_result if isinstance(exc, GDriveSyncError) else None
        if result and args.json:
            print(json.dumps(result.__dict__, indent=2, sort_keys=True))
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result.__dict__, indent=2, sort_keys=True))
    else:
        print(
            f"{result.operation}: ok, files created={len(result.created_files)}, "
            f"updated={len(result.updated_files)}, deleted={len(result.deleted_entries)}, "
            f"conflicts={len(result.conflicts)}, warnings={len(result.warnings)}, "
            f"bytes={result.bytes_transferred}, elapsed={result.elapsed_seconds:.1f}s"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
