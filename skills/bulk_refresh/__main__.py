import typer
from typing import Optional

from lib.cli import run_command
from lib.logger import get_logger
from skills.bulk_refresh.bulk_refresh import bulk_refresh

logger = get_logger(__name__)
app = typer.Typer(help="Automatically refreshes caches and profiles for all SICTIC members and startups in bulk.")

@app.command()
def main(
    dataset: Optional[str] = typer.Option(None, "--dataset", "-d", help="Specific dataset to refresh (e.g., sictic_members, avientus). If none, all datasets are refreshed."),
    skill: Optional[str] = typer.Option(None, "--skill", "-s", help="Specific skill to refresh (e.g., person_profile, startup_profile). If none, all are refreshed.")
):
    run_command(
        lambda: bulk_refresh(target_dataset=dataset, target_skill=skill),
        logger=logger,
        error_prefix="Bulk refresh failed",
    )

if __name__ == "__main__":
    app()
