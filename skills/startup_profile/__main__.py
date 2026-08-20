from dataclasses import dataclass
from typing import List, Optional

import typer

from lib.cli import format_insights, run_command
from lib.insights import InsightFile
from lib.logger import get_logger
from skills.startup_profile.startup_profile import startup_profile

logger = get_logger(__name__)



app = typer.Typer(help="Generates a neutral, objective 5-point diagnostic of a startup.")


@dataclass(frozen=True)
class StartupProfileBatchResult:
    insights: list[InsightFile]
    successful_startups: list[str]
    failures: list[tuple[str, str]]


async def _profile_startups(
    startups: list[str],
    files: Optional[List[str]],
) -> StartupProfileBatchResult:
    insights: list[InsightFile] = []
    successful_startups: list[str] = []
    failures: list[tuple[str, str]] = []
    for startup in startups:
        logger.info("Starting profile generation for startup: %s", startup)
        try:
            insights.extend(await startup_profile(startup, files))
        except Exception as error:
            logger.exception(
                "Startup profile failed for %s; continuing with the next "
                "startup: %s",
                startup,
                error,
            )
            failures.append((startup, str(error)))
            continue
        successful_startups.append(startup)

    return StartupProfileBatchResult(
        insights=insights,
        successful_startups=successful_startups,
        failures=failures,
    )

@app.command()
def profile_startup(
    startup: str = typer.Option(
        ...,
        "--startup",
        "-s",
        help="Comma-separated startup names",
    ),
    files: Optional[List[str]] = typer.Option(
        None,
        "--files",
        "-f",
        help="Optional list of PDF/document files",
    ),
):
    startups = [name.strip() for name in startup.split(",") if name.strip()]
    if not startups:
        raise typer.BadParameter("Provide at least one startup name.")

    batch_result = run_command(
        lambda: _profile_startups(startups, files),
        logger=logger,
        error_prefix="Execution failed",
    )
    typer.echo("\n--- Profile Output ---\n")
    typer.echo(format_insights(batch_result.insights))
    typer.echo("\n----------------------\n")
    logger.info(
        "Startup profile batch completed: %d requested, %d successful, "
        "%d failed, %d insight(s) produced",
        len(startups),
        len(batch_result.successful_startups),
        len(batch_result.failures),
        len(batch_result.insights),
    )
    if batch_result.failures:
        typer.echo("Failed startups:", err=True)
        for startup_name, error in batch_result.failures:
            typer.echo(f"- {startup_name}: {error}", err=True)
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
