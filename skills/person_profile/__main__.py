import typer
from skills.person_profile.person_profile import person_profile
from lib.logger import get_logger

logger = get_logger(__name__)
app = typer.Typer(help="CLI for person_profile skill")

@app.command()
def main(
    person: str = typer.Option(..., "--person", "-p", help="The person's name (e.g. 'John Doe')."),
    dataset: str = typer.Option(..., "--dataset", "-d", help="The target dataset to search.")
):
    import asyncio
    try:
        persons = asyncio.run(person_profile(dataset_name=dataset, names=person))
        for p in persons:
            print(p.person_profile)
    except typer.Exit:
        raise
    except Exception as e:
        logger.error(str(e))
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
