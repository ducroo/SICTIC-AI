import typer
from typing import Optional, List
from skills.utils.logger import get_logger
from skills.potential_investors.potential_investors import potential_investors

logger = get_logger(__name__)
app = typer.Typer(add_completion=False)

@app.command()
def main(
    startup_name: str = typer.Argument(..., help="The name of the startup to match."),
    target_investors: str = typer.Option(None, help="Comma-separated list of investor names. Leave empty for all members."),
    exclude_investors: str = typer.Option(None, help="Comma-separated list of investor names to exclude."),
    top_k: int = typer.Option(8, help="Number of top investors to return.")
):
    """
    Provides a ranked list of potential investors for a given startup based on semantic matching and LLM refinement.
    """
    import asyncio
    
    parsed_targets = [name.strip() for name in target_investors.split(",")] if target_investors else None
    parsed_excludes = [name.strip() for name in exclude_investors.split(",")] if exclude_investors else None
    
    try:
        result = asyncio.run(potential_investors(
            startup_name=startup_name,
            target_investors=parsed_targets,
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