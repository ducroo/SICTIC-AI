import typer

from lib.cli import run_command
from lib.logger import get_logger
from skills.sictic_git_sync.sictic_git_sync import sictic_git_sync

logger = get_logger(__name__)
app = typer.Typer(
    add_completion=False,
    help="Synchronize OpenClaw workspace skills with the SICTIC-AI repository.",
)


@app.command()
def main(
    action: str = typer.Option(
        ...,
        "--action",
        help="Synchronization action: push, pull, status, or reconcile.",
    ),
    message: str = typer.Option(
        "auto-sync skills",
        "--message",
        help="Commit message for the push action.",
    ),
) -> None:
    if action not in {"push", "pull", "status", "reconcile"}:
        raise typer.BadParameter(
            "must be push, pull, status, or reconcile",
            param_hint="--action",
        )
    result = run_command(
        lambda: sictic_git_sync(action=action, message=message),
        logger=logger,
    )
    typer.echo("\n" + result)

if __name__ == "__main__":
    app()
