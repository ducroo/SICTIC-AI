from typing import Optional

import typer

from lib.cli import format_insights, run_command
from lib.infrastructure.logging import get_logger
from skills.application_feedback.application_feedback import (
    EmailMode,
    application_feedback,
)

logger = get_logger(__name__)
app = typer.Typer(
    help=(
        "Review open Dealum applications and draft feedback emails for the "
        "screener. Reads from Dealum only and never writes to it."
    )
)


@app.command()
def run_application_feedback(
    startups: Optional[list[str]] = typer.Option(
        None,
        "--startups",
        "-s",
        help=(
            "Startup name or Dealum application code. Repeat for multiple "
            "startups; omit to process all applications in the stage "
            "Application."
        ),
    ),
    email: EmailMode = typer.Option(
        EmailMode.OFF,
        "--email",
        case_sensitive=False,
        help=(
            "Email the summary to SCREENER_EMAILS when there are new, "
            "changed or undelivered drafts or failures: off, dry-run (save the email instead) "
            "or send."
        ),
    ),
):
    result = run_command(
        lambda: application_feedback(startups or None, email=email),
        logger=logger,
        error_prefix="Execution failed",
    )
    typer.echo(format_insights(result))


if __name__ == "__main__":
    app()
