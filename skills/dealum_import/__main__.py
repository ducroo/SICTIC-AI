import asyncio

import typer

from skills.dealum_import.dealum_import import dealum_import

app = typer.Typer(help="Import a startup application and linked documents from Dealum.")


@app.command()
def main(startup: str):
    startups = [name.strip() for name in startup.split(",") if name.strip()]
    if not startups:
        raise typer.BadParameter("Provide at least one startup name.")

    failed = False
    for name in startups:
        try:
            result = asyncio.run(dealum_import(name))
        except Exception as error:
            typer.echo(f"Failed to import {name}: {error}", err=True)
            failed = True
            continue

        if not result.application_found:
            typer.echo(f"No Dealum application found for {name}.", err=True)
            failed = True
            continue

        typer.echo(
            f"Imported {result.dataset_slug}: changed={result.changed}, "
            f"downloaded={result.downloaded_files}, skipped={result.skipped_files}, "
            f"step={result.step}"
        )
        if result.application_path:
            typer.echo(f"APPLICATION_PATH: {result.application_path}")
        if result.manifest_path:
            typer.echo(f"MANIFEST_PATH: {result.manifest_path}")

    if failed:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
