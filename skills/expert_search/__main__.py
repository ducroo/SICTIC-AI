import typer

from lib.cli import format_insights, run_command
from lib.infrastructure.logging import get_logger
from skills.expert_search.expert_search import expert_search

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

    result = run_command(
        lambda: expert_search(
            startup_name=startup,
            target_experts=parsed_includes,
            exclude_experts=parsed_excludes,
            top_k=top_k
        ),
        logger=logger,
    )
    typer.echo("\n--- Expert Search Result ---\n")
    typer.echo(format_insights(result))

if __name__ == "__main__":
    app()
