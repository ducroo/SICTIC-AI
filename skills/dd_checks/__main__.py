import typer

from lib.cli import run_command
from lib.logger import get_logger
from skills.dd_checks.dd_checks import dd_checks

logger = get_logger(__name__)



app = typer.Typer(help="Performs a comprehensive M&A-style due diligence review of a startup's data room.")

@app.command()
def run_dd_checks(
    startup: str = typer.Option(..., "--startup", "-s", help="Name of the startup")
):
    output_file = run_command(
        lambda: dd_checks(startup),
        logger=logger,
        error_prefix="Execution failed",
    )
    typer.echo(f"DD checks complete. Output saved to {output_file}")

if __name__ == "__main__":
    app()
