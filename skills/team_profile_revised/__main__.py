import typer

from lib.cli import format_insights, run_command
from lib.infrastructure.logging import get_logger
from skills.team_profile_revised.team_profile_revised import team_profile_revised

logger = get_logger(__name__)
app = typer.Typer(help="Assess founder-team checklists and synthesize each category.")


@app.command()
def run_team_profile_revised(
    dataset_name: str = typer.Option(..., "--dataset", "-d", help="Target startup dataset."),
):
    insights = run_command(
        lambda: team_profile_revised(dataset_name),
        logger=logger,
        error_prefix="Execution failed",
    )
    typer.echo(format_insights(insights))


if __name__ == "__main__":
    app()
