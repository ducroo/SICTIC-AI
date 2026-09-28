from __future__ import annotations

import typer

from lib.cli import run_command
from lib.infrastructure.logging import get_logger
from skills.startup_website_import.startup_website_import import (
    startup_website_import,
)

logger = get_logger(__name__)
app = typer.Typer(help="Import a startup public website into dataset storage.")


@app.command()
def main(
    startup_name: str = typer.Argument(..., metavar="STARTUP", help="Startup name for the dataset."),
    url: str | None = typer.Argument(None, help="Website URL; otherwise resolve from dataset evidence."),
    depth: int | None = typer.Option(None, "--depth", min=0, help="Internal crawl depth; default from shared configuration."),
    max_pages: int | None = typer.Option(
        None,
        "--max-pages",
        min=1,
        help="Maximum HTML pages to import.",
    ),
    include_pdfs: bool | None = typer.Option(
        None,
        "--pdfs/--no-pdfs",
        help="Download same-domain PDFs linked from crawled pages.",
    ),
    max_pdfs: int | None = typer.Option(
        None,
        "--max-pdfs",
        min=0,
        help="Maximum PDF files to download.",
    ),
    max_pdf_mb: int | None = typer.Option(
        None,
        "--max-pdf-mb",
        min=1,
        help="Maximum size per PDF download.",
    ),
    respect_robots: bool | None = typer.Option(
        None,
        "--respect-robots/--ignore-robots",
        help="Respect robots.txt when available.",
    ),
) -> None:
    result = run_command(
        lambda: startup_website_import(
            startup_name,
            url,
            depth=depth,
            max_pages=max_pages,
            include_pdfs=include_pdfs,
            max_pdfs=max_pdfs,
            max_pdf_mb=max_pdf_mb,
            respect_robots=respect_robots,
        ),
        logger=logger,
        error_prefix="Website import failed",
    )
    if result.skipped_reason:
        typer.echo(f"Skipped website for {result.dataset_slug}: {result.skipped_reason}")
        return
    typer.echo(f"Imported website for {result.dataset_slug}")
    typer.echo(f"WEBSITE_PATH: {result.website_path}")
    typer.echo(f"HTML_PAGES: {result.pages_saved}")
    typer.echo(f"PDFS: {result.pdfs_saved}")
    typer.echo(f"LINKEDIN_URLS: {result.linkedin_urls_found}")
    typer.echo(f"LINKEDIN_URLS_PATH: {result.linkedin_urls_path}")
    typer.echo(f"FAILED_PAGES: {result.failed_pages}")
    typer.echo(f"LINK_MANIFEST: {result.link_manifest_path}")


if __name__ == "__main__":
    app()
