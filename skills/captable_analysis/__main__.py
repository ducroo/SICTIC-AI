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


if __name__ == "__main__":
    app()
