import typer

from lib.cli import format_insights, run_command
from lib.infrastructure.logging import get_logger
from skills.application_feedback.application_feedback import EmailMode, application_feedback

logger = get_logger(__name__)
app = typer.Typer(
    help=(
        "Draft and email feedback for one startup with a fresh submission review."
    )
)


@app.command()
def run_application_feedback(
    startup: str = typer.Option(..., "--startup", "-s", help="Name of the startup"),
    email: EmailMode = typer.Option(
        EmailMode.SEND, "--email", case_sensitive=False,
        help="Send to configured reviewers, or save the draft only with off/dry-run.",
    ),
):
    insights = run_command(
        lambda: application_feedback(startup, email=email),
        logger=logger,
        error_prefix="Execution failed",
    )
    typer.echo(format_insights(insights))


if __name__ == "__main__":
    app()
