import typer

from lib.cli import format_insights, run_command
from lib.logger import get_logger
from skills.person_profile.person_profile import person_profile

logger = get_logger(__name__)
app = typer.Typer(help="CLI for person_profile skill")

@app.command()
def main(
    dataset: str = typer.Option(..., "--dataset", "-d", help="The target dataset to search."),
    person: str = typer.Option(None, "--person", "-p", help="The person's name (e.g. 'John Doe'). Leave empty to profile all persons in the dataset.")
):
    insights = run_command(
        lambda: person_profile(dataset_name=dataset, names=person),
        logger=logger,
    )
    typer.echo(format_insights(insights))

if __name__ == "__main__":
    app()
