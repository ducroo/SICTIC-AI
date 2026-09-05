import json

import typer

from lib.cli import run_command
from lib.infrastructure.logging import get_logger
from skills.captable_analysis.captable_analysis import captable_analysis

logger = get_logger(__name__)
app = typer.Typer(
    help="Analyze a stored cap-table snapshot (scenarios, rubric, narrative)."
)


@app.command("run")
def run_cmd(
    dataset_name: str = typer.Option(
        ..., "--dataset", "-d", help="Target startup dataset name."
    ),
    as_of: str = typer.Option(
        None, "--as-of", help="Analyze a specific snapshot (default: latest)."
    ),
    pre_money: float = typer.Option(
        None, "--pre-money", help="Hypothetical round pre-money valuation."
    ),
    investment: float = typer.Option(
        None, "--investment", help="Hypothetical round size."
    ),
):
    result = run_command(
        lambda: captable_analysis(
            dataset_name,
            as_of=as_of,
            pre_money=pre_money,
            investment=investment,
        ),
        logger=logger,
        error_prefix="Analysis failed",
    )
    typer.echo(json.dumps(result["computed"], ensure_ascii=False, indent=2))
    typer.echo("\n---\n")
    typer.echo(result["narrative"])


@app.command("render")
def render_cmd(
    dataset_name: str = typer.Option(
        ..., "--dataset", "-d", help="Target startup dataset name."
    ),
    as_of: str = typer.Option(
        None, "--as-of", help="Render a specific snapshot (default: latest)."
    ),
):
    """Render the snapshot as a self-contained HTML page (no LLM call)."""
    from skills.captable_analysis.captable_analysis import render_captable

    result = run_command(
        lambda: render_captable(dataset_name, as_of=as_of),
        logger=logger,
        error_prefix="Render failed",
    )
    typer.echo(
        f"Rendered {result['path']} (scenarios included: "
        f"{result['scenarios_included']})"
    )


if __name__ == "__main__":
    app()
