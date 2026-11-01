import typer

from lib.cli import format_insights, run_command
from lib.infrastructure.logging import get_logger
from skills.application_feedback.application_feedback import application_feedback

logger = get_logger(__name__)
app = typer.Typer(
    help=(
        "Draft the feedback email for one startup from its latest submission "
        "review. Run submission_ready first."
    )
)


@app.command()
def run_application_feedback(
    startup: str = typer.Option(..., "--startup", "-s", help="Name of the startup"),
):
    insights = run_command(
        lambda: application_feedback(startup),
        logger=logger,
        error_prefix="Execution failed",
    )
    typer.echo(format_insights(insights))


if __name__ == "__main__":
    app()
