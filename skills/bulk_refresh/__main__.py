import typer
from typing import Optional

from lib.cli import run_command
from lib.infrastructure.logging import get_logger
from skills.bulk_refresh.bulk_refresh import bulk_refresh

logger = get_logger(__name__)
app = typer.Typer(help="Automatically refreshes caches and profiles for all SICTIC members and startups in bulk.")

@app.command()
def main(
    datasets: Optional[str] = typer.Option(
        None,
        "--datasets",
        "-d",
        help=(
            "Comma-separated source datasets, or 'all'. "
            "Defaults to active startup and community datasets."
        ),
    ),
    skills: Optional[str] = typer.Option(
        None,
        "--skills",
        "-s",
        help=(
            "Comma-separated root skills, or 'all'. "
            "Required dependencies are included automatically."
        ),
    ),
):
    run_command(
        lambda: bulk_refresh(datasets=datasets, skills=skills),
        logger=logger,
        error_prefix="Bulk refresh failed",
    )

if __name__ == "__main__":
    app()
