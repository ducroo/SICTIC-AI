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
    startup_name: str = typer.Argument(..., help="Startup name for the dataset."),
    url: str = typer.Argument(..., help="Public startup website URL."),
    depth: int = typer.Option(1, "--depth", min=0, help="Internal crawl depth."),
    max_pages: int = typer.Option(
        50,
        "--max-pages",
        min=1,
        help="Maximum HTML pages to import.",
    ),
    include_pdfs: bool = typer.Option(
        True,
        "--pdfs/--no-pdfs",
        help="Download same-domain PDFs linked from crawled pages.",
    ),
    max_pdfs: int = typer.Option(
        20,
        "--max-pdfs",
        min=0,
        help="Maximum PDF files to download.",
    ),
    max_pdf_mb: int = typer.Option(
        25,
        "--max-pdf-mb",
        min=1,
        help="Maximum size per PDF download.",
    ),
    respect_robots: bool = typer.Option(
        True,
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
