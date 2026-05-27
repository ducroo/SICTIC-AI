import typer
import asyncio
from skills.expert_search.expert_search import expert_search
from lib.logger import get_logger

logger = get_logger(__name__)
app = typer.Typer(help="Find expert individuals for a startup.")

@app.command()
def main(
    startup: str = typer.Option(..., "--startup", "-s", help="Name of the startup"),
    include: str = typer.Option(None, "--include", "-i", help="Comma-separated list of expert IDs to restrict the search to"),
    exclude: str = typer.Option(None, "--exclude", "-x", help="Comma-separated list of expert IDs to exclude"),
    top_k: int = typer.Option(8, "--top-k", "-k", help="Number of top experts to return")
):
    parsed_includes = [x.strip() for x in include.split(",")] if include else None
    parsed_excludes = [x.strip() for x in exclude.split(",")] if exclude else None

    try:
        result = asyncio.run(expert_search(
            startup_name=startup,
            target_experts=parsed_includes,
            exclude_experts=parsed_excludes,
            top_k=top_k
        ))
        print("\n--- Expert Search Result ---\n")
        print(result)
    except Exception as e:
        logger.error(f"Error: {e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
