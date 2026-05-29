"""Hydrate selected person-profile insights into the searchable profile dataset.

This script does not generate profiles. It reuses existing markdown insights,
selects the preferred model output per person via RANKED_LLMS, materializes
those selections in derived/person-profile, and forces Qdrant ingestion.
"""
from __future__ import annotations

import asyncio
from typing import Optional

import typer

from lib.dataset_from_insight import DatasetFromInsightResult, dataset_from_insight

app = typer.Typer(help="Sync existing person profile insights into Qdrant.")


async def sync_person_profiles_from_insights(
    *,
    source_dataset: str = "sictic-members",
    target_dataset: str = "person_profile",
    reset_qdrant: bool = False,
    dry_run: bool = False,
) -> DatasetFromInsightResult:
    result = await dataset_from_insight(
        target_dataset=target_dataset,
        insight="person_profile",
        source_dataset=source_dataset,
        dry_run=dry_run,
    )

    if dry_run:
        return result

    if reset_qdrant:
        from skills.dataset_chat.dataset_delete import dataset_delete

        dataset_delete(dataset=target_dataset)

    from skills.dataset_chat.core.ingestion import sync_datasets

    await sync_datasets([target_dataset], raise_on_error=True, force=True)
    return result


def _print_result(result: DatasetFromInsightResult, *, reset_qdrant: bool) -> None:
    mode = "DRY-RUN" if result.dry_run else "SYNC"
    typer.echo(f"Mode: {mode}")
    typer.echo(f"Source dataset: {result.source_dataset or 'all active datasets'}")
    typer.echo(f"Target dataset: {result.target_dataset}")
    typer.echo(f"Target path: {result.target_path}")
    typer.echo(f"Candidate insight files: {result.candidates}")
    typer.echo(f"Entities evaluated: {result.entities}")
    typer.echo(f"Profiles selected: {result.selected}")
    typer.echo(f"Files synced: {result.synced}")
    typer.echo(f"Files removed: {result.removed}")
    typer.echo(f"Files unchanged: {result.unchanged}")
    if reset_qdrant and not result.dry_run:
        typer.echo("Qdrant reset: yes")


@app.command()
def main(
    source_dataset: str = typer.Option("sictic-members", "--source-dataset", help="Dataset whose insight folder contains person profiles."),
    target_dataset: str = typer.Option("person_profile", "--target-dataset", help="Derived dataset to hydrate and index."),
    reset_qdrant: bool = typer.Option(False, "--reset-qdrant", help="Delete the target Qdrant dataset before re-indexing."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report what would change without writing or indexing."),
) -> None:
    result = asyncio.run(
        sync_person_profiles_from_insights(
            source_dataset=source_dataset,
            target_dataset=target_dataset,
            reset_qdrant=reset_qdrant,
            dry_run=dry_run,
        )
    )
    _print_result(result, reset_qdrant=reset_qdrant)


if __name__ == "__main__":
    app()
