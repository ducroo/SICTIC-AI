import typer
import asyncio
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
    try:
        result = asyncio.run(investor_profile(source_dataset=source_dataset))
        typer.echo(f"Source dataset: {result.source_dataset}")
        typer.echo(f"Person profiles: {result.person_profiles}")
        typer.echo(f"Written: {result.written}")
        typer.echo(f"Unchanged: {result.unchanged}")
        typer.echo(f"Skipped: {result.skipped}")
        typer.echo(f"Missing track records: {result.missing_track_records}")
    except Exception as e:
        logger.error(f"Execution failed: {e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
