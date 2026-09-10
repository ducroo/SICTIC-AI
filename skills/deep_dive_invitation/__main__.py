import typer

from lib.cli import format_insights, run_command
from lib.infrastructure.logging import get_logger
from skills.deep_dive_invitation.deep_dive_invitation import (
    deep_dive_invitation,
    parse_people_csv,
)

logger = get_logger(__name__)
app = typer.Typer(help="Create a review-only deep-dive invitation draft.")


@app.command()
def main(
    startup: str = typer.Option(..., "--startup", "-s", help="Exact Dealum name or code."),
    founders: str = typer.Option(
        "",
        "--founders",
        help="Comma-separated founders as Name <email>, email, or name.",
    ),
    investors: str = typer.Option(
        "",
        "--investors",
        help="Comma-separated investors as Name <email>, email, or name.",
    ),
) -> None:
    insights = run_command(
        lambda: deep_dive_invitation(
            startup,
            founders=parse_people_csv(founders),
            investors=parse_people_csv(investors),
        ),
        logger=logger,
        error_prefix="Deep-dive invitation failed",
    )
    typer.echo(format_insights(insights))


if __name__ == "__main__":
    app()
