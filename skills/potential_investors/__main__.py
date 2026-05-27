import typer
import asyncio
from lib.logger import get_logger
from skills.potential_investors.potential_investors import potential_investors

logger = get_logger(__name__)
app = typer.Typer(add_completion=False, help="Provides a ranked list of potential investors for a given startup.")

@app.command()
def main(
    startup: str = typer.Option(..., "--startup", "-s", help="The name of the startup to match."),
    include: str = typer.Option(None, "--include", "-i", help="Comma-separated list of investor names to include."),
    exclude: str = typer.Option(None, "--exclude", "-x", help="Comma-separated list of investor names to exclude."),
    top_k: int = typer.Option(8, "--top-k", "-k", help="Number of top investors to return.")
):
    parsed_includes = [name.strip() for name in include.split(",")] if include else None
    parsed_excludes = [name.strip() for name in exclude.split(",")] if exclude else None
    
    try:
        result = asyncio.run(potential_investors(
            startup_name=startup,
            target_investors=parsed_includes,
            exclude_investors=parsed_excludes,
            top_k=top_k
        ))
        pass # Output is saved to file and logged, GUI catches it natively
    except Exception as e:
        logger.error(f"Execution failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
