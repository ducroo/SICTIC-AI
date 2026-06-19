from __future__ import annotations

import typer

from lib.insights import InsightHydrationResult


def print_hydration_result(result: InsightHydrationResult) -> None:
    mode = "DRY-RUN" if result.dry_run else "SYNC"
    typer.echo(f"Mode: {mode}")
    typer.echo(
        f"Source dataset: "
        f"{result.source_dataset or 'all active datasets'}"
    )
    typer.echo(f"Target dataset: {result.target_dataset}")
    typer.echo(f"Target path: {result.target_path}")
    typer.echo(f"Insight: {result.insight}")
    typer.echo(f"Candidate insight files: {result.candidates}")
    typer.echo(f"Entities evaluated: {result.entities}")
    typer.echo(f"Profiles selected: {result.selected}")
    typer.echo(f"Files synced: {result.synced}")
    typer.echo(f"Files removed: {result.removed}")
    typer.echo(f"Files unchanged: {result.unchanged}")
