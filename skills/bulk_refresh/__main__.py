import typer
from typing import Optional

from lib.cli import run_command
from lib.infrastructure.logging import get_logger
from skills.bulk_refresh.bulk_refresh import bulk_refresh

logger = get_logger(__name__)
app = typer.Typer(help="Update dataset states and incrementally refresh stage-mandatory or selected skills.")

@app.command()
def main(
    datasets: Optional[str] = typer.Option(
        None,
        "--datasets",
        "-d",
        help=(
            "Comma-separated source datasets, or 'all'. "
            "Named missing startups are created only for always-active Dealum stages. "
            "Defaults to active startup and community datasets, or all when --exclude is supplied."
        ),
    ),
    skills: Optional[str] = typer.Option(
        None,
        "--skills",
        "-s",
        help=(
            "Comma-separated root skills, or 'all'. "
            "Defaults to mandatory skills for each dataset's stage. "
            "Required dependencies are included automatically."
        ),
    ),
    exclude: Optional[str] = typer.Option(
        None,
        "--exclude",
        help="Comma-separated source datasets to exclude. Unknown names are rejected.",
    ),
):
    run_command(
        lambda: bulk_refresh(datasets=datasets, skills=skills, exclude=exclude),
        logger=logger,
        error_prefix="Bulk refresh failed",
    )

if __name__ == "__main__":
    app()
