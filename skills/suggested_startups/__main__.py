import typer
from typing import List, Optional

from lib.cli import format_insights, run_command
from lib.logger import get_logger
from skills.suggested_startups.suggested_startups import suggested_startups

logger = get_logger(__name__)

app = typer.Typer(help="CLI for suggested_startups skill")

@app.command()
def main(
    startups: Optional[List[str]] = typer.Option(None, "--startups", "-s", help="List of startup names. If omitted, discovered from insights."),
    investors: Optional[List[str]] = typer.Option(None, "--investors", "-i", help="List of investor names. If omitted, discovered from insights."),
    max_startups: int = typer.Option(5, "--max-startups", "-m", help="Maximum number of startups to suggest per investor.")
):
    result = run_command(
        lambda: suggested_startups(
            startups=startups,
            investors=investors,
            max_startups=max_startups
        ),
        logger=logger,
        error_prefix="Execution failed",
    )
    typer.echo(format_insights(result))

if __name__ == "__main__":
    app()
