from pathlib import Path

import typer

from lib.cli import run_command
from lib.logger import get_logger
from skills.dd_checks_agent.dd_checks_agent import save_report

logger = get_logger(__name__)
app = typer.Typer(
    help="Persist an agent-orchestrated dd_checks Markdown report as an InsightFile."
)


@app.command()
def main(
    dataset: str = typer.Argument(..., help="Dataset the report was generated for."),
    content_file: Path = typer.Option(
        ..., "--content-file", help="Path to the Markdown report content to persist."
    ),
    prompt_key: str = typer.Option(
        "dd_checks_agent-v1",
        "--prompt-key",
        help="Freshness/cache key recorded for this report.",
    ),
):
    logger.info("Saving agent-orchestrated dd_checks report for %s", dataset)
    result = run_command(
        lambda: save_report(
            dataset, content_file.read_text(encoding="utf-8"), prompt_key
        ),
        logger=logger,
        error_prefix="Failed to save dd_checks_agent report",
    )
    typer.echo(result)


if __name__ == "__main__":
    app()
