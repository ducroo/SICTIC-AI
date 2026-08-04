from pathlib import Path

import typer

from lib.cli import run_command
from lib.insights import InsightFile
from lib.logger import get_logger

logger = get_logger(__name__)
app = typer.Typer(
    help="Persist an agent-orchestrated dd_checks Markdown report as an InsightFile."
)


@app.command()
def main(
    dataset: str = typer.Argument(..., help="Dataset the report was generated for."),
    content_file: Path = typer.Option(
        ..., "--content-file", help="Path to the Markdown report content to persist."
    ),
    prompt_key: str = typer.Option(
        "dd_checks_agent-v1",
        "--prompt-key",
        help="Freshness/cache key recorded for this report.",
    ),
):
    def save() -> str:
        insight = InsightFile(
            dataset=dataset,
            skill="dd_checks",
            model="anthropic/claude-code-agent",
            prompt_key=prompt_key,
        )
        insight.save(content_file.read_text(encoding="utf-8"))
        return insight.path

    result = run_command(
        save, logger=logger, error_prefix="Failed to save dd_checks_agent report"
    )
    typer.echo(result)


if __name__ == "__main__":
    app()
