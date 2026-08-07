import typer

from lib.cli import format_insights, run_command
from lib.logger import get_logger
from skills.startup_traction.startup_traction import startup_traction

logger = get_logger(__name__)
app = typer.Typer(help="CLI for startup_traction skill")

@app.command()
def main(
    startup: str = typer.Option(..., "--startup", "-s", help="The name of the startup to analyze.")
):
    result = run_command(
        lambda: startup_traction(startup),
        logger=logger,
        error_prefix="Execution failed",
    )
    typer.echo(format_insights(result))

if __name__ == "__main__":
    app()
