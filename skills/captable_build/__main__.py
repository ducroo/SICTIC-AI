import json

import typer

from lib.cli import run_command
from lib.infrastructure.logging import get_logger
from skills.captable_build.captable_build import classify, extract

logger = get_logger(__name__)
app = typer.Typer(
    help="Build structured cap-table/CLA facts for one startup dataset."
)


@app.command("classify")
def classify_cmd(
    dataset_name: str = typer.Option(
        ..., "--dataset", "-d", help="Target startup dataset name."
    ),
):
    """Classify every document of the dataset (stage 1)."""
    result = run_command(
        lambda: classify(dataset_name),
        logger=logger,
        error_prefix="Classification failed",
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("extract")
def extract_cmd(
    dataset_name: str = typer.Option(
        ..., "--dataset", "-d", help="Target startup dataset name."
    ),
):
    """Extract terms from every classified CLA document (stage 2)."""
    result = run_command(
        lambda: extract(dataset_name),
        logger=logger,
        error_prefix="CLA extraction failed",
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
