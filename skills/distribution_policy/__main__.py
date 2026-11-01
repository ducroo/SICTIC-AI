import typer

from lib.cli import format_insights, run_command
from lib.infrastructure.logging import get_logger
from skills.distribution_policy.distribution_policy import (
    EmailMode,
    requested_insights,
    screener_feedback,
)

logger = get_logger(__name__)
app = typer.Typer(help="Email SICTIC insights according to the distribution rules.")


@app.command("screener-feedback")
def run_screener_feedback(
    email: EmailMode = typer.Option(
        EmailMode.OFF,
        "--email",
        case_sensitive=False,
        help=(
            "Email the summary to SCREENER_EMAILS when there are new, changed "
            "or undelivered drafts or applications that are not ready: off, "
            "dry-run (save the email instead) or send."
        ),
    ),
):
    """Summarize the feedback drafts of open applications for the screeners."""
    insights = run_command(
        lambda: screener_feedback(email=email),
        logger=logger,
        error_prefix="Execution failed",
    )
    typer.echo(format_insights(insights))


@app.command("requested")
def run_requested(
    insights: list[str] = typer.Argument(
        ..., help="Requested Markdown insight files, absolute or storage-relative.",
    ),
    to: str = typer.Option(..., "--to", help="Email address of the requester."),
    requester_agreed: bool = typer.Option(
        False,
        "--requester-agreed",
        help="Confirm that the requester asked for this email.",
    ),
):
    """Email requested insights in full to the person who asked for them."""
    run_command(
        lambda: requested_insights(insights, to, requester_agreed=requester_agreed),
        logger=logger,
        error_prefix="Execution failed",
    )
    typer.echo(f"Emailed {len(insights)} insight(s) to {to}.")


if __name__ == "__main__":
    app()
