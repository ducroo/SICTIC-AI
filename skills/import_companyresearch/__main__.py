"""CLI for a single import or a sweep of all outstanding requests."""

from dataclasses import asdict
import json

import typer

from lib.cli import run_command
from lib.infrastructure.logging import get_logger
from . import import_companyresearch

logger = get_logger(__name__)
app = typer.Typer(help="Import CompanyResearch once, or collect pending reports without waiting.")


@app.command()
def main(
    startup: str | None = typer.Argument(None, help="Destination startup; omit to sweep only."),
    uid: str | None = typer.Option(None, "--uid", help="Explicit Swiss UID; bypasses discovery."),
    company_name: str | None = typer.Option(None, "--company-name", help="Name to use for registry lookup."),
):
    results = run_command(lambda: import_companyresearch(startup, uid=uid, company_name=company_name),
                          logger=logger, error_prefix="CompanyResearch import failed")
    typer.echo(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))
    if any(result.status in ("error", "failed", "cancelled", "expired") for result in results):
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
