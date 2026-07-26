import typer

from lib.cli import run_command
from lib.logger import get_logger
from skills.submission_ready.submission_ready import submission_ready

logger = get_logger(__name__)
app = typer.Typer(
    help="Check a startup's Dealum submission for completeness and eligibility."
)


@app.command()
def run_submission_ready(
    startup: str = typer.Option(..., "--startup", "-s", help="Name of the startup")
):
    output_file = run_command(
        lambda: submission_ready(startup),
        logger=logger,
        error_prefix="Execution failed",
    )
    typer.echo(f"Submission readiness check complete. Output saved to {output_file}")


if __name__ == "__main__":
    app()
