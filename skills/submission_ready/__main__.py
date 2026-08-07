from typing import Optional

import typer

from lib.cli import format_insights, run_command
from lib.logger import get_logger
from skills.submission_ready.submission_ready import submission_ready

logger = get_logger(__name__)
app = typer.Typer(
    help="Check a startup's Dealum submission for completeness and eligibility."
)


@app.command()
def run_submission_ready(
    startup: Optional[list[str]] = typer.Option(
        None,
        "--startup",
        "-s",
        help=(
            "Startup name. Repeat for multiple startups; omit to process "
            "all Application and Under review submissions."
        ),
    ),
):
    result = run_command(
        lambda: submission_ready(startup or None),
        logger=logger,
        error_prefix="Execution failed",
    )
    typer.echo(format_insights(result))


if __name__ == "__main__":
    app()
