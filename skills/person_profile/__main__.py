import typer
from typing import Optional

from lib.cli import format_insights, run_command
from lib.logger import get_logger
from skills.person_profile.person_profile import person_profile

logger = get_logger(__name__)
app = typer.Typer(help="CLI for person_profile skill")

@app.command()
def main(
    dataset: str = typer.Option(..., "--dataset", "-d", help="The target dataset to search."),
    person: Optional[str] = typer.Option(
        None,
        "--person",
        "-p",
        help=(
            "Comma-separated person names to profile; "
            "omit it to profile everyone in the dataset."
        ),
    ),
):
    names = None
    if person is not None:
        names = [name.strip() for name in person.split(",") if name.strip()]
        if not names:
            raise typer.BadParameter("Provide at least one person name.")

    insights = run_command(
        lambda: person_profile(dataset_name=dataset, names=names),
        logger=logger,
    )
    typer.echo(format_insights(insights))

if __name__ == "__main__":
    app()
