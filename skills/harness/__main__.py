import sys
import typer
from typing import Optional, List

from lib.cli import run_command
from lib.runtime_noise import configure_runtime_noise

configure_runtime_noise()

from lib.infrastructure.logging import get_logger
from lib.litellm_cleanup import close_litellm_sessions
from skills.harness.harness import dispatch_command, run

logger = get_logger(__name__)
app = typer.Typer(help="Lightweight slash-command CLI harness for SICTIC-AI skills.")

INTERACTIVE_CONDA_HINT = (
    "Interactive harness mode requires a live terminal stdin. "
    "Use `conda run -n sictic-env --no-capture-output python -m skills.harness`, "
    "or activate the environment first and run `python -m skills.harness`."
)


async def _dispatch_one_shot(command: str) -> str:
    try:
        return await dispatch_command(command)
    finally:
        await close_litellm_sessions()


@app.command()
def main(
    command: Optional[List[str]] = typer.Argument(
        None,
        help='Optional one-shot slash command, for example: /help or /startup_profile avientus.'
    )
):
    if command:
        output = run_command(
            lambda: _dispatch_one_shot(" ".join(command)),
            logger=logger,
            error_prefix="Harness failed",
        )
        if output and output != "__EXIT__":
            typer.echo(output)
        return
    if not sys.stdin.isatty():
        typer.echo(INTERACTIVE_CONDA_HINT, err=True)
        raise typer.Exit(code=2)
    run_command(run, logger=logger, error_prefix="Harness failed")


if __name__ == "__main__":
    app()
