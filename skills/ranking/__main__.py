import typer
import asyncio
from skills.ranking.ranking_persons import ranking_persons
from lib.logger import get_logger

logger = get_logger(__name__)
app = typer.Typer(help="Ranking module for SICTIC-AI")

@app.command()
def main(
    target: str = typer.Option("persons", "--target", "-t", help="What entity to rank"),
    objective: str = typer.Option(..., "--objective", "-o", help="The objective/criteria for ranking"),
    query: str = typer.Option("", "--query", "-q", help="Semantic search query to fetch candidates"),
    top_k: int = typer.Option(8, "--top-k", "-k", help="Number of top candidates to return")
):
    if target == "persons":
        try:
            result = asyncio.run(ranking_persons(
                objective=objective,
                query=query,
                top_k=top_k
            ))
            print("\n\n" + result)
        except Exception as e:
            logger.error(f"Error: {e}")
            raise typer.Exit(code=1)
    else:
        print(f"Target '{target}' is not yet implemented.")

if __name__ == "__main__":
    app()
