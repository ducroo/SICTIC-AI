import typer

from lib.cli import format_insights, run_command
from lib.infrastructure.logging import get_logger
from skills.dataroom_review.dataroom_review import dataroom_review

logger = get_logger(__name__)
app = typer.Typer(help="Review a data-room dossier already stored in a dataset.")


@app.command()
def run_dataroom_review(
    dataset_name: str = typer.Option(
        ...,
        "--dataset",
        "-d",
        help="Dataset that contains the data-room files.",
    ),
):
    insights = run_command(
        lambda: dataroom_review(dataset_name),
        logger=logger,
        error_prefix="Execution failed",
    )
    typer.echo(format_insights(insights))


if __name__ == "__main__":
    app()
