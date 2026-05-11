import typer
from typing import Optional
from skills.bulk_refresh.bulk_refresh import bulk_refresh
from skills.utils.logger import get_logger

logger = get_logger(__name__)
app = typer.Typer(help="Automatically refreshes caches and profiles for all SICTIC members and startups in bulk.")

@app.command()
def main(
    dataset: Optional[str] = typer.Option(None, "--dataset", "-d", help="Specific dataset to refresh (e.g., sictic_members, avientus). If none, all datasets are refreshed."),
    skill: Optional[str] = typer.Option(None, "--skill", "-s", help="Specific skill to refresh (e.g., person_profile, startup_profile). If none, all are refreshed.")
):
    try:
        import asyncio
        asyncio.run(bulk_refresh(target_dataset=dataset, target_skill=skill))
    except Exception as e:
        logger.error(f"Bulk refresh failed: {e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
