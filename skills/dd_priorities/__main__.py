import typer

from lib.cli import run_command
from lib.logger import get_logger
from skills.dd_priorities.dd_priorities import dd_priorities

logger = get_logger(__name__)
app = typer.Typer(
    help="Synthesize an existing DD checks report into prioritized concerns."
)


@app.command()
def run_dd_priorities(
    startup: str = typer.Option(..., "--startup", "-s", help="Name of the startup")
):
    output_file = run_command(
        lambda: dd_priorities(startup),
        logger=logger,
        error_prefix="Execution failed",
    )
    typer.echo(f"DD priorities complete. Output saved to {output_file}")


if __name__ == "__main__":
    app()
