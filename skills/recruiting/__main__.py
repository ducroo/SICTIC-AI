from pathlib import Path

import typer

from lib.cli import format_insights, run_command
from lib.infrastructure.logging import get_logger
from skills.recruiting import recruiting

app = typer.Typer(help="Assess applicants against shared job criteria.")
logger = get_logger(__name__)


@app.command()
def main(
    dataset: str = typer.Option(..., "--dataset", "-d"),
    criteria: str | None = typer.Option(None, "--criteria", help="Job advert or criteria text."),
    criteria_file: Path | None = typer.Option(
        None, "--criteria-file", exists=True, dir_okay=False,
        help="UTF-8 text/Markdown job advert or criteria.",
    ),
):
    if criteria is not None and criteria_file is not None:
        raise typer.BadParameter("Use either --criteria or --criteria-file.")
    supplied = criteria_file.read_text(encoding="utf-8") if criteria_file else criteria
    result = run_command(lambda: recruiting(dataset, supplied), logger=logger)
    typer.echo(format_insights(result))


if __name__ == "__main__":
    app()
