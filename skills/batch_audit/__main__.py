from pathlib import Path

import typer

from lib.cli import run_command
from lib.logger import get_logger
from skills.batch_audit.batch_audit import batch_audit

logger = get_logger(__name__)
app = typer.Typer(help="Run a Markdown checklist against a dataset.")


@app.command()
def main(
    dataset: str = typer.Argument(..., help="Dataset to audit."),
    checklist_file: Path = typer.Argument(..., help="Markdown checklist file."),
    skill_name: str = typer.Option(
        "batch_audit",
        "--skill-name",
        help="Calling skill used as the output filename prefix.",
    ),
):
    result = run_command(
        lambda: batch_audit(
            dataset,
            checklist_file.read_text(encoding="utf-8"),
            skill_name=skill_name,
        ),
        logger=logger,
        error_prefix="Execution failed",
    )
    typer.echo(result.path)


if __name__ == "__main__":
    app()
