import typer
from lib.cli import format_insights, run_command
from lib.infrastructure.logging import get_logger
from skills.advocates.advocates import advocates

logger = get_logger(__name__)
app = typer.Typer(help="Find SICTIC members to act as advocates for an event.")

@app.command()
def main(
    event: str = typer.Option(..., "--event", "-e", help="Short name of the event"),
    description: str = typer.Option(..., "--description", "-d", help="Detailed description of the event and skills required"),
    include: str = typer.Option(None, "--include", "-i", help="Comma-separated list of member IDs to restrict the search to"),
    exclude: str = typer.Option(None, "--exclude", "-x", help="Comma-separated list of member IDs to exclude"),
    top_k: int = typer.Option(16, "--top-k", "-k", help="Number of top advocates to return")
):
    parsed_includes = [x.strip() for x in include.split(",")] if include else None
    parsed_excludes = [x.strip() for x in exclude.split(",")] if exclude else None

    result = run_command(
        lambda: advocates(
            event_name=event,
            event_description=description,
            target_members=parsed_includes,
            exclude_members=parsed_excludes,
            top_k=top_k
        ),
        logger=logger,
    )
    typer.echo("\n--- Advocates Result ---\n")
    typer.echo(format_insights(result))

if __name__ == "__main__":
    app()
