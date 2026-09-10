import typer
from lib.cli import format_insights, run_command
from lib.infrastructure.logging import get_logger
from skills.persons_in_dataset.persons_in_dataset import persons_in_dataset

app = typer.Typer(help="Discover and maintain a dataset's editable person roster.")
logger = get_logger(__name__)

@app.command()
def main(dataset: str = typer.Option(..., "--dataset", "-d")):
    insights = run_command(lambda: persons_in_dataset(dataset), logger=logger)
    typer.echo(format_insights(insights) if insights else "No related people found; no roster created.")

if __name__ == "__main__":
    app()
