import typer

from lib.cli import format_insights, run_command
from lib.infrastructure.logging import get_logger
from skills.potential_investors.potential_investors import potential_investors

logger = get_logger(__name__)
app = typer.Typer(add_completion=False, help="Provides a ranked list of potential investors for a given startup.")

@app.command()
def main(
    startup: str = typer.Option(..., "--startup", "-s", help="The name of the startup to match."),
    include: str = typer.Option(None, "--include", "-i", help="Comma-separated list of investor names to include."),
    exclude: str = typer.Option(None, "--exclude", "-x", help="Comma-separated list of investor names to exclude."),
    top_k: int = typer.Option(16, "--top-k", "-k", help="Number of top investors to return.")
):
    parsed_includes = [name.strip() for name in include.split(",")] if include else None
    parsed_excludes = [name.strip() for name in exclude.split(",")] if exclude else None
    
    result = run_command(
        lambda: potential_investors(
            startup_name=startup,
            target_investors=parsed_includes,
            exclude_investors=parsed_excludes,
            top_k=top_k
        ),
        logger=logger,
        error_prefix="Execution failed",
    )
    typer.echo(format_insights(result))

if __name__ == "__main__":
    app()
