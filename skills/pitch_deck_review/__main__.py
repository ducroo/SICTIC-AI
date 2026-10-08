import typer

from lib.cli import format_insights, run_command
from lib.infrastructure.logging import get_logger
from skills.pitch_deck_review.pitch_deck_review import pitch_deck_review

logger = get_logger(__name__)
app = typer.Typer(
    help="Review a pitch deck already stored in a dataset."
)


@app.command()
def run_pitch_deck_review(
    dataset_name: str = typer.Option(
        ...,
        "--dataset",
        "-d",
        help="Dataset that contains the pitch deck.",
    ),
):
    insights = run_command(
        lambda: pitch_deck_review(dataset_name),
        logger=logger,
        error_prefix="Execution failed",
    )
    typer.echo(format_insights(insights))


if __name__ == "__main__":
    app()
