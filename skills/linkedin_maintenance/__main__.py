from __future__ import annotations

import json
from typing import Optional

import typer

from lib.cli import run_command
from lib.logger import get_logger
from skills.linkedin_maintenance.maintenance import (
    diagnose_registry,
    import_profiles,
    missing_profile_urls,
    missing_profiles,
)

logger = get_logger(__name__)
app = typer.Typer(
    add_completion=False,
    help="Manual LinkedIn profile scraping and registry maintenance.",
)


@app.command()
def missing() -> None:
    result = run_command(missing_profiles, logger=logger)
    typer.echo("\n".join(missing_profile_urls(result)))


@app.command("import")
def import_command(
    file_path: str = typer.Argument(...),
    dataset: Optional[str] = typer.Option(None, "--dataset", "-d"),
) -> None:
    count = run_command(
        lambda: import_profiles(file_path, dataset),
        logger=logger,
    )
    typer.echo(f"Imported {count} LinkedIn profiles.")


@app.command()
def diagnose() -> None:
    result = run_command(diagnose_registry, logger=logger)
    typer.echo(json.dumps(result, indent=2))


if __name__ == "__main__":
    app()
