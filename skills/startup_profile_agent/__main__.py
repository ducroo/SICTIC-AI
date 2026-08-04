from pathlib import Path

import typer

from lib.cli import run_command
from lib.logger import get_logger
from skills.startup_profile_agent.startup_profile_agent import save_report

logger = get_logger(__name__)
app = typer.Typer(
    help="Persists an agent-authored startup profile report through InsightFile."
)


@app.command()
def main(
    dataset: str = typer.Argument(..., help="Startup dataset name"),
    content_file: Path = typer.Option(
        ...,
        "--content-file",
        help="Path to the Markdown report content written by the invoking agent",
    ),
    prompt_key: str = typer.Option(
        "startup_profile_agent-v1",
        "--prompt-key",
        help="Prompt/version key recorded for insight freshness tracking",
    ),
) -> None:
    logger.info("Saving agent-orchestrated startup profile for %s", dataset)
    result = run_command(
        lambda: save_report(
            dataset, content_file.read_text(encoding="utf-8"), prompt_key
        ),
        logger=logger,
        error_prefix="Failed to save startup profile report",
    )
    typer.echo(result)


if __name__ == "__main__":
    app()
