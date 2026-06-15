from __future__ import annotations

import json
from dataclasses import asdict

from .client import GDriveSync
from .types import ConflictPolicy, OperationResult


def run_operation(
    operation: str,
    *,
    dry_run: bool = False,
    conflict_policy: ConflictPolicy = "local-wins",
    local_root: str | None = None,
    cloud_root: str | None = None,
    credentials_path: str | None = None,
    token_path: str | None = None,
    state_dir: str | None = None,
    log_dir: str | None = None,
    exclude: list[str] | None = None,
    lock_timeout: float = 1800,
    verbose: bool = False,
) -> OperationResult:
    syncer = GDriveSync(
        local_root=local_root,
        gdrive_root=cloud_root,
        credentials_path=credentials_path,
        token_path=token_path,
        exclude=exclude,
        lock_timeout=lock_timeout,
        state_dir=state_dir,
        log_dir=log_dir,
        verbose=verbose,
    )
    if operation == "push":
        return syncer.push(dry_run=dry_run)
    if operation == "pull":
        return syncer.pull(dry_run=dry_run)
    if operation == "sync":
        return syncer.sync(conflict_policy=conflict_policy, dry_run=dry_run)
    raise ValueError(f"Unsupported gdrive_sync operation: {operation}")


def format_result(result: OperationResult, *, as_json: bool) -> str:
    if as_json:
        return json.dumps(asdict(result), indent=2, sort_keys=True)
    return (
        f"{result.operation}: ok, files created={len(result.created_files)}, "
        f"updated={len(result.updated_files)}, deleted={len(result.deleted_entries)}, "
        f"conflicts={len(result.conflicts)}, warnings={len(result.warnings)}, "
        f"bytes={result.bytes_transferred}, elapsed={result.elapsed_seconds:.1f}s"
    )
