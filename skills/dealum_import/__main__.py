import asyncio

import typer

from skills.dealum_import.dealum_import import dealum_import

app = typer.Typer(help="Import a startup application and linked documents from Dealum.")


@app.command()
def main(startup: str):
    result = asyncio.run(dealum_import(startup))
    if not result.application_found:
        typer.echo(f"No Dealum application found for {startup}.")
        raise typer.Exit(code=1)
    typer.echo(
        f"Imported {result.dataset_slug}: changed={result.changed}, "
        f"downloaded={result.downloaded_files}, skipped={result.skipped_files}, "
        f"step={result.step}"
    )
    if result.application_path:
        typer.echo(f"APPLICATION_PATH: {result.application_path}")
    if result.manifest_path:
        typer.echo(f"MANIFEST_PATH: {result.manifest_path}")


if __name__ == "__main__":
    app()
