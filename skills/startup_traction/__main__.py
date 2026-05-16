import typer
from skills.startup_traction.startup_traction import startup_traction
from lib.logger import get_logger

logger = get_logger(__name__)

app = typer.Typer(help="CLI for startup_traction skill")

@app.command()
def main(startup_name: str = typer.Argument(..., help="The name of the startup to analyze. This directly corresponds to the dataset name.")):
    try:
        result = startup_traction(startup_name)
        print(result)
    except ValueError as e:
        logger.error(str(e))
        print(f"Error: {e}")
        raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as e:
        logger.error(f"Execution failed: {e}")
        print(f"Error: {e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
