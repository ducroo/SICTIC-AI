from pathlib import Path

import typer

from lib.cli import run_command
from lib.insights.file import InsightFile
from lib.logger import get_logger

logger = get_logger(__name__)

app = typer.Typer(
    help="Persists an agent-authored startup profile report through InsightFile."
)


@app.command()
def save_report(
    dataset: str = typer.Argument(..., help="Startup dataset name"),
    content_file: Path = typer.Option(
        ...,
        "--content-file",
        help="Path to the Markdown report content written by the invoking agent",
    ),
    prompt_key: str = typer.Option(
        "startup_profile_agent-v1",
        "--prompt-key",
        help="Prompt/version key recorded for insight freshness tracking",
    ),
) -> None:
    def _save() -> str:
        logger.info("Saving agent-orchestrated startup profile for %s", dataset)
        content = content_file.read_text(encoding="utf-8")
        insight = InsightFile(
            dataset=dataset,
            skill="startup_profile",
            model="anthropic/claude-code-agent",
            prompt_key=prompt_key,
        )
        insight.save(content)
        return insight.path

    path = run_command(
        _save,
        logger=logger,
        error_prefix="Failed to save startup profile report",
    )
    typer.echo(path)


if __name__ == "__main__":
    app()
