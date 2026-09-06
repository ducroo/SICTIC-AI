import typer
from typing import List, Optional

from lib.cli import format_insights, run_command
from lib.infrastructure.logging import get_logger
from skills.suggested_startups.suggested_startups import suggested_startups

logger = get_logger(__name__)

app = typer.Typer(help="CLI for suggested_startups skill")

@app.command()
def main(
    startups: Optional[List[str]] = typer.Option(None, "--startups", "-s", help="Repeat for each startup name. If omitted, use startup datasets, excluding configured community and ignored datasets."),
    investor: Optional[str] = typer.Option(
        None,
        "--investor",
        "-i",
        help=(
            "Comma-separated investor names or LinkedIn IDs. If omitted, use "
            "eligible people from the existing roster."
        ),
    ),
    max_startups: int = typer.Option(16, "--max-startups", "-m", help="Maximum number of startups to suggest per investor.")
):
    investors = None
    if investor is not None:
        investors = [
            name.strip()
            for name in investor.split(",")
            if name.strip()
        ]
        if not investors:
            raise typer.BadParameter("Provide at least one investor name.")

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
