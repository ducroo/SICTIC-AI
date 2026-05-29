import typer
import asyncio
from skills.dd_checks.dd_checks import dd_checks
from lib.logger import get_logger

logger = get_logger(__name__)



app = typer.Typer(help="Performs a comprehensive M&A-style due diligence review of a startup's data room.")

@app.command()
def run_dd_checks(
    startup: str = typer.Option(..., "--startup", "-s", help="Name of the startup")
):
    try:
        output_file = asyncio.run(dd_checks(startup))
        print(f"DD checks complete. Output saved to {output_file}")
    except Exception as e:
        logger.error(f"Execution failed: {e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
