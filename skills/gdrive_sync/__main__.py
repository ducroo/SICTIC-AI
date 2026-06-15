from __future__ import annotations

from typing import Optional

import typer

from lib.logger import get_logger
from skills.gdrive_sync.cli import format_result, run_operation
from skills.gdrive_sync.types import GDriveSyncError

logger = get_logger(__name__)
app = typer.Typer(
    add_completion=False,
    help="Synchronize local application storage with Google Drive.",
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
def push(
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
        "push", dry_run, json_output, local_root, cloud_root, credentials_path,
        token_path, state_dir, log_dir, exclude or [], lock_timeout, verbose,
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
