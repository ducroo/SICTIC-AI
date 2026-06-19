import typer
from typing import Optional, List

from lib.cli import run_command
from lib.runtime_noise import configure_runtime_noise

configure_runtime_noise()

from lib.logger import get_logger
from lib.litellm_cleanup import close_litellm_sessions
from skills.harness.harness import dispatch_command, run

logger = get_logger(__name__)
app = typer.Typer(help="Lightweight slash-command CLI harness for SICTIC-AI skills.")


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
    run_command(run, logger=logger, error_prefix="Harness failed")


if __name__ == "__main__":
    app()
