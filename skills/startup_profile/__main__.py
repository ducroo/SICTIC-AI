import typer
from typing import List, Optional

from lib.cli import format_insights, run_command
from lib.logger import get_logger
from skills.startup_profile.startup_profile import startup_profile

logger = get_logger(__name__)



app = typer.Typer(help="Generates a neutral, objective 5-point diagnostic of a startup.")

@app.command()
def profile_startup(
    startup: str = typer.Option(..., "--startup", "-s", help="Name of the startup"),
    files: Optional[List[str]] = typer.Option(None, "--files", "-f", help="Optional list of PDF/document files")
):
    logger.info("Starting profile generation for startup: %s", startup)
    insights = run_command(
        lambda: startup_profile(startup, files),
        logger=logger,
        error_prefix="Execution failed",
    )
    typer.echo("\n--- Profile Output ---\n")
    typer.echo(format_insights(insights))
    typer.echo("\n----------------------\n")
    logger.info("Successfully produced %d startup profile insight(s)", len(insights))

if __name__ == "__main__":
    app()
