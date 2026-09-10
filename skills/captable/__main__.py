import typer

from lib.cli import run_command, format_insights
from lib.infrastructure.logging import get_logger
from skills.captable.captable import captable

logger = get_logger(__name__)
app = typer.Typer(
    help="Analyze consolidated cap-table data (scenarios, rubric, narrative)."
)


@app.command("run")
def run_cmd(
    dataset_name: str = typer.Option(
        ..., "--startup", "--dataset", "-s", "-d", help="Target startup dataset name."
    ),
    pre_money: float = typer.Option(
        None, "--pre-money", help="Hypothetical round pre-money valuation."
    ),
    investment: float = typer.Option(
        None, "--investment", help="Hypothetical round size."
    ),
    fx_rate: list[str] = typer.Option(
        None,
        "--fx-rate",
        help=(
            "FX rate for a loan currency as CUR=RATE, units of the scenario "
            "currency per 1 CUR (e.g. USD=0.88). Repeatable. Required for "
            "every loan currency that differs from the scenario currency."
        ),
    ),
    currency: str = typer.Option(
        None,
        "--currency",
        help=(
            "Scenario currency (default: the loans' common currency, else "
            "CHF)."
        ),
    ),
):
    from skills.captable.captable import parse_fx_rates

    result = run_command(
        lambda: captable(
            dataset_name,
            pre_money=pre_money,
            investment=investment,
            fx_rates=parse_fx_rates(fx_rate),
            currency=currency,
        ),
        logger=logger,
        error_prefix="Analysis failed",
    )
    typer.echo(format_insights(result))


@app.callback()
def main():
    """Analyze consolidated cap-table data as Markdown."""


if __name__ == "__main__":
    app()
