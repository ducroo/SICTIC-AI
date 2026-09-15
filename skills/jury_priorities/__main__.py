import typer

from lib.cli import format_insights, run_command
from lib.infrastructure.logging import get_logger
from skills.jury_priorities.jury_priorities import jury_priorities

logger = get_logger(__name__)
app = typer.Typer(
    help="Format an existing saved rating report into a non-ratable jury briefing."
)


@app.command()
def run_jury_priorities(
    startup: str = typer.Option(..., "--startup", "-s", help="Name of the startup")
):
    insights = run_command(
        lambda: jury_priorities(startup),
        logger=logger,
        error_prefix="Execution failed",
    )
    typer.echo(format_insights(insights))


if __name__ == "__main__":
    app()
