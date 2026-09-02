import typer

from lib.cli import format_insights, run_command
from lib.infrastructure.logging import get_logger
from skills.team_profile.team_profile import team_profile

logger = get_logger(__name__)

app = typer.Typer(help="Performs deep-dive due diligence on a startup's leadership.")

@app.command()
def profile_team(
    startup: str = typer.Option(..., "--startup", "-s", help="Name of the startup")
):
    logger.info("Starting team profile generation for startup: %s", startup)
    insights = run_command(
        lambda: team_profile(startup),
        logger=logger,
        error_prefix="Execution failed",
    )
    typer.echo("\n--- Team Profile Output ---\n")
    typer.echo(format_insights(insights))
    typer.echo("\n---------------------------\n")
    logger.info("Successfully produced %d team profile insight(s)", len(insights))

if __name__ == "__main__":
    app()
