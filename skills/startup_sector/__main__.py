import typer

from lib.cli import format_insights, run_command
from lib.infrastructure.logging import get_logger
from skills.startup_sector import startup_sector

logger = get_logger(__name__)
app = typer.Typer(help="Classify a startup with four provider taxonomies.")


@app.command()
def main(
    startup: str = typer.Option(
        ..., "--startup", "-s", help="Startup name or prepared temporary dataset name.",
    ),
):
    result = run_command(
        lambda: startup_sector(startup), logger=logger, error_prefix="Execution failed",
    )
    typer.echo(format_insights(result))


if __name__ == "__main__":
    app()
