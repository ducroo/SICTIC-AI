from __future__ import annotations

import json
from dataclasses import asdict
from typing import Optional

import typer

from lib.logger import get_logger
from skills.gdrive_sync.client import GDriveSync
from skills.gdrive_sync.types import ConflictPolicy, GDriveSyncError, OperationResult

logger = get_logger(__name__)
app = typer.Typer(
    add_completion=False,
    help="Synchronize local application storage with Google Drive.",
)


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


def _execute(
    operation: str,
    *,
    dry_run: bool,
    json_output: bool,
    conflict_policy: str = "local-wins",
    local_root: Optional[str],
    cloud_root: Optional[str],
    credentials_path: Optional[str],
    token_path: Optional[str],
    state_dir: Optional[str],
    log_dir: Optional[str],
    exclude: list[str],
    lock_timeout: float,
    verbose: bool,
) -> None:
    try:
        result = run_operation(
            operation,
            dry_run=dry_run,
            conflict_policy=conflict_policy,
            local_root=local_root,
            cloud_root=cloud_root,
            credentials_path=credentials_path,
            token_path=token_path,
            state_dir=state_dir,
            log_dir=log_dir,
            exclude=exclude,
            lock_timeout=lock_timeout,
            verbose=verbose,
        )
        typer.echo(format_result(result, as_json=json_output))
    except (GDriveSyncError, ValueError) as exc:
        if isinstance(exc, GDriveSyncError) and exc.partial_result and json_output:
            typer.echo(format_result(exc.partial_result, as_json=True))
        logger.error(str(exc))
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


def _common_options(
    operation: str,
    dry_run: bool,
    json_output: bool,
    local_root: Optional[str],
    cloud_root: Optional[str],
    credentials_path: Optional[str],
    token_path: Optional[str],
    state_dir: Optional[str],
    log_dir: Optional[str],
    exclude: list[str],
    lock_timeout: float,
    verbose: bool,
    conflict_policy: str = "local-wins",
) -> None:
    _execute(
        operation,
        dry_run=dry_run,
        json_output=json_output,
        conflict_policy=conflict_policy,
        local_root=local_root,
        cloud_root=cloud_root,
        credentials_path=credentials_path,
        token_path=token_path,
        state_dir=state_dir,
        log_dir=log_dir,
        exclude=exclude,
        lock_timeout=lock_timeout,
        verbose=verbose,
    )


@app.command()
def pull(
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_output: bool = typer.Option(False, "--json"),
    local_root: Optional[str] = typer.Option(None, "--local-root"),
    cloud_root: Optional[str] = typer.Option(None, "--cloud-root"),
    credentials_path: Optional[str] = typer.Option(None, "--credentials-path"),
    token_path: Optional[str] = typer.Option(None, "--token-path"),
    state_dir: Optional[str] = typer.Option(None, "--state-dir"),
    log_dir: Optional[str] = typer.Option(None, "--log-dir"),
    exclude: Optional[list[str]] = typer.Option(None, "--exclude"),
    lock_timeout: float = typer.Option(1800, "--lock-timeout"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    _common_options(
        "pull", dry_run, json_output, local_root, cloud_root, credentials_path,
        token_path, state_dir, log_dir, exclude or [], lock_timeout, verbose,
    )


@app.command()
def sync(
    local_wins: bool = typer.Option(False, "--local-wins"),
    cloud_wins: bool = typer.Option(False, "--cloud-wins"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_output: bool = typer.Option(False, "--json"),
    local_root: Optional[str] = typer.Option(None, "--local-root"),
    cloud_root: Optional[str] = typer.Option(None, "--cloud-root"),
    credentials_path: Optional[str] = typer.Option(None, "--credentials-path"),
    token_path: Optional[str] = typer.Option(None, "--token-path"),
    state_dir: Optional[str] = typer.Option(None, "--state-dir"),
    log_dir: Optional[str] = typer.Option(None, "--log-dir"),
    exclude: Optional[list[str]] = typer.Option(None, "--exclude"),
    lock_timeout: float = typer.Option(1800, "--lock-timeout"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    if local_wins == cloud_wins:
        raise typer.BadParameter("choose exactly one of --local-wins or --cloud-wins")
    _common_options(
        "sync", dry_run, json_output, local_root, cloud_root, credentials_path,
        token_path, state_dir, log_dir, exclude or [], lock_timeout, verbose,
        conflict_policy="local-wins" if local_wins else "cloud-wins",
    )


if __name__ == "__main__":
    app()
