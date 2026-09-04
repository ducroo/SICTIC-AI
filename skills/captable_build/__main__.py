import json

import typer

from lib.cli import run_command
from lib.infrastructure.logging import get_logger
from skills.captable_build.captable_build import (
    aggregate,
    assess,
    build,
    classify,
    extract,
    snapshot,
    table,
)

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


@app.command("assess")
def assess_cmd(
    dataset_name: str = typer.Option(
        ..., "--dataset", "-d", help="Target startup dataset name."
    ),
):
    """Deterministically assess every extracted CLA (stage 3)."""
    result = run_command(
        lambda: assess(dataset_name),
        logger=logger,
        error_prefix="CLA assessment failed",
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("aggregate")
def aggregate_cmd(
    dataset_name: str = typer.Option(
        ..., "--dataset", "-d", help="Target startup dataset name."
    ),
):
    """Aggregate all extracted CLAs of the dataset (stage 4)."""
    result = run_command(
        lambda: aggregate(dataset_name),
        logger=logger,
        error_prefix="CLA aggregation failed",
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("table")
def table_cmd(
    dataset_name: str = typer.Option(
        ..., "--dataset", "-d", help="Target startup dataset name."
    ),
):
    """Extract cap table, share register, and pools (stage 5)."""
    result = run_command(
        lambda: table(dataset_name),
        logger=logger,
        error_prefix="Table extraction failed",
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("snapshot")
def snapshot_cmd(
    dataset_name: str = typer.Option(
        ..., "--dataset", "-d", help="Target startup dataset name."
    ),
):
    """Validate and store the versioned snapshot (stages 6-7)."""
    result = run_command(
        lambda: snapshot(dataset_name),
        logger=logger,
        error_prefix="Snapshot failed",
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("build")
def build_cmd(
    dataset_name: str = typer.Option(
        ..., "--dataset", "-d", help="Target startup dataset name."
    ),
    fresh: bool = typer.Option(
        False, "--fresh", help="Discard stored work products first."
    ),
):
    """Run the full pipeline, stages 1-7."""
    result = run_command(
        lambda: build(dataset_name, fresh=fresh),
        logger=logger,
        error_prefix="Build failed",
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
