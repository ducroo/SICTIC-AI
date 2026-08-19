import typer

from lib.cli import run_command
from lib.logger import get_logger
from skills.ranking.ranking_persons import ranking_persons

logger = get_logger(__name__)
app = typer.Typer(help="Ranking module for SICTIC-AI")

@app.command()
def main(
    target: str = typer.Option("persons", "--target", "-t", help="What entity to rank"),
    objective: str = typer.Option(..., "--objective", "-o", help="The objective/criteria for ranking"),
    top_k: int = typer.Option(8, "--top-k", "-k", help="Number of top candidates to return")
):
    if target == "persons":
        result = run_command(
            lambda: ranking_persons(
                objective=objective,
                top_k=top_k
            ),
            logger=logger,
        )
        typer.echo("\n\n" + result)
    else:
        typer.echo(f"Target '{target}' is not yet implemented.")

if __name__ == "__main__":
    app()
