import typer
from skills.person_profile.person_profile import person_profile
from skills.utils.logger import get_logger

logger = get_logger(__name__)

app = typer.Typer(help="CLI for person_profile skill")

@app.command()
def main(
    name: str = typer.Argument(..., help="The person's name (e.g. 'John Doe')."),
    dataset_name: str = typer.Argument(..., help="The target dataset to search.")
):
    import asyncio
    try:
        result = asyncio.run(person_profile(dataset_name=dataset_name, name=name))
        print(result)
    except typer.Exit:
        raise
    except Exception as e:
        logger.error(str(e))
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()