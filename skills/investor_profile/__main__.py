import typer

from lib.cli import format_insights, run_command
from lib.logger import get_logger
from skills.investor_profile.investor_profile import investor_profile

logger = get_logger(__name__)
app = typer.Typer(add_completion=False, help="Build investor profiles from person profiles and track records.")

@app.command()
def main(
    source_dataset: str = typer.Option(
        "sictic-members",
        "--source-dataset",
        help="Community dataset containing person profiles and track records.",
    ),
):
    result = run_command(
        lambda: investor_profile(source_dataset=source_dataset),
        logger=logger,
        error_prefix="Execution failed",
    )
    typer.echo(format_insights(result))

if __name__ == "__main__":
    app()
