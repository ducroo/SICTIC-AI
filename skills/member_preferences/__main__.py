import typer

from lib.cli import run_command
from lib.infrastructure.logging import get_logger
from skills.member_preferences.member_preferences import (
    member_preferences,
    render_member_preferences,
)

logger = get_logger(__name__)
app = typer.Typer(help="Return the member roster with communication preferences.")


@app.command()
def main(
    dataset: str = typer.Option(
        "sictic-members",
        "--dataset",
        "-d",
        help="Member dataset to enrich.",
    ),
) -> None:
    people = run_command(lambda: member_preferences(dataset), logger=logger)
    typer.echo(render_member_preferences(people))


if __name__ == "__main__":
    app()
