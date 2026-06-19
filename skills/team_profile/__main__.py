import typer

from lib.cli import run_command
from lib.logger import get_logger
from skills.team_profile.team_profile import team_profile

logger = get_logger(__name__)

app = typer.Typer(help="Performs deep-dive due diligence on a startup's leadership.")

@app.command()
def profile_team(
    startup: str = typer.Option(..., "--startup", "-s", help="Name of the startup")
):
    logger.info("Starting team profile generation for startup: %s", startup)
    profile_output, output_file = run_command(
        lambda: team_profile(startup),
        logger=logger,
        error_prefix="Execution failed",
    )
    typer.echo("\n--- Team Profile Output ---\n")
    typer.echo(profile_output)
    typer.echo("\n---------------------------\n")
    logger.info("Successfully saved team profile to %s", output_file)

if __name__ == "__main__":
    app()
