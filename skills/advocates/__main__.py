import typer
import asyncio
from skills.advocates.advocates import advocates
from lib.logger import get_logger

logger = get_logger(__name__)
app = typer.Typer(help="Find SICTIC members to act as advocates for an event.")

@app.command()
def main(
    event: str = typer.Option(..., "--event", "-e", help="Short name of the event"),
    description: str = typer.Option(..., "--description", "-d", help="Detailed description of the event and skills required"),
    include: str = typer.Option(None, "--include", "-i", help="Comma-separated list of member IDs to restrict the search to"),
    exclude: str = typer.Option(None, "--exclude", "-x", help="Comma-separated list of member IDs to exclude"),
    top_k: int = typer.Option(10, "--top-k", "-k", help="Number of top advocates to return")
):
    parsed_includes = [x.strip() for x in include.split(",")] if include else None
    parsed_excludes = [x.strip() for x in exclude.split(",")] if exclude else None

    try:
        result = asyncio.run(advocates(
            event_name=event,
            event_description=description,
            target_members=parsed_includes,
            exclude_members=parsed_excludes,
            top_k=top_k
        ))
        print("\n--- Advocates Result ---\n")
        print(result)
    except Exception as e:
        logger.error(f"Error: {e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
