import typer

from lib.cli import format_insights, run_command
from lib.logger import get_logger
from skills.sha_review.sha_review import sha_review

logger = get_logger(__name__)
app = typer.Typer(
    help="Review the best substantive Shareholders' Agreement candidate in a dataset."
)


@app.command()
def run_sha_review(
    dataset_name: str = typer.Option(
        ...,
        "--dataset",
        "-d",
        help="Target startup dataset name.",
    ),
):
    insights = run_command(
        lambda: sha_review(dataset_name),
        logger=logger,
        error_prefix="Execution failed",
    )
    typer.echo(format_insights(insights))


if __name__ == "__main__":
    app()
