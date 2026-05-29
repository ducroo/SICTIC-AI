import typer
import asyncio
from typing import Optional, List

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
    try:
        if command:
            output = asyncio.run(_dispatch_one_shot(" ".join(command)))
            if output and output != "__EXIT__":
                print(output)
            return
        run()
    except Exception as e:
        logger.error(f"Harness failed: {e}")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
