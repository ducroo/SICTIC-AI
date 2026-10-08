import typer

from lib.cli import format_insights, run_command
from lib.infrastructure.logging import get_logger
from skills.cla_review.cla_review import cla_review

logger = get_logger(__name__)
app = typer.Typer(
    help="Review one convertible-loan term sheet from the lender's side, in the context of the startup's cap table, existing loans and SHA."
)


@app.command()
def run_cla_review(
    startup: str = typer.Option(
        ...,
        "--startup",
        "--dataset",
        "-s",
        "-d",
        help="Target startup dataset name.",
    ),
    document: str | None = typer.Option(
        None,
        "--document",
        help="Data-room path of the term sheet to review; omitted, the model selects the most recent CLA term sheet.",
    ),
    ticket: float | None = typer.Option(
        None,
        "--ticket",
        help="The member's own loan amount in the term sheet currency; omitted, an evidenced per-member minimum or a labelled scenario assumption is used.",
    ),
    fresh: bool = typer.Option(
        False,
        "--fresh",
        help="Bypass reuse of generated artifacts (manual files still take precedence).",
    ),
):
    insights = run_command(
        lambda: cla_review(startup, document=document, ticket=ticket, fresh=fresh),
        logger=logger,
        error_prefix="Execution failed",
    )
    typer.echo(format_insights(insights))


if __name__ == "__main__":
    app()
