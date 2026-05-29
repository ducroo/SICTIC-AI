import typer
import asyncio
from typing import List, Optional
from skills.suggested_startups.suggested_startups import suggested_startups
from lib.logger import get_logger

logger = get_logger(__name__)

app = typer.Typer(help="CLI for suggested_startups skill")

@app.command()
def main(
    startups: Optional[List[str]] = typer.Option(None, "--startups", "-s", help="List of startup names. If omitted, discovered from insights."),
    investors: Optional[List[str]] = typer.Option(None, "--investors", "-i", help="List of investor names. If omitted, discovered from insights."),
    max_startups: int = typer.Option(5, "--max-startups", "-m", help="Maximum number of startups to suggest per investor.")
):
    try:
        # We pass startups and investors directly; suggested_startups will resolve defaults
        result = asyncio.run(suggested_startups(
            startups=startups,
            investors=investors,
            max_startups=max_startups
        ))
        print(result)
    except ValueError as e:
        logger.error(str(e))
        print(f"Error: {e}")
        raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as e:
        logger.error(f"Execution failed: {e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
