"""CLI for conversion only; the skill uses gws separately to send."""
from pathlib import Path

import typer

from lib.cli import run_command
from lib.infrastructure.logging import get_logger
from .render_email import convert_file

app = typer.Typer()
logger = get_logger(__name__)


@app.command()
def main(
    source: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    output: Path | None = typer.Option(None, "--output", dir_okay=False),
) -> None:
    """Convert a Markdown file to email HTML and print its output path."""
    path = run_command(lambda: convert_file(source, output), logger=logger)
    typer.echo(str(path))


if __name__ == "__main__":
    app()
