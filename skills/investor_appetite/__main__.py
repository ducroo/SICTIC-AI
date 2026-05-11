import typer
from typing import Optional, List
from skills.utils.logger import get_logger
from skills.investor_appetite.investor_appetite import investor_appetite

logger = get_logger(__name__)
app = typer.Typer(add_completion=False)

@app.command()
def main(investors: Optional[List[str]] = typer.Argument(None, help="List of investor names. Leave empty for all members.")):
    """
    Determines the ideal startup profile for one or more investors based on their personal profiles.
    """
    try:
        results = investor_appetite(investors=investors)
        for name, profile in results.items():
            # Standard output format as per guidelines
            pass # Output is saved to files and logged, GUI will catch the result dict natively
    except Exception as e:
        logger.error(f"Execution failed: {e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()