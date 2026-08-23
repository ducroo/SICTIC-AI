from __future__ import annotations

from typing import Optional

import typer

from lib.cli import run_command
from lib.datasets.ingestion import sync_datasets
from lib.insights import dataset_from_insight
from lib.logger import get_logger
from skills.dataset_maintenance.maintenance import (
    activate_dataset_marker,
    archive_dataset_marker,
    delete_dataset_index,
    diagnose_qdrant_collections,
    prune_orphaned_qdrant_collections,
    rebuild_dataset_index,
)
from lib.startups.dossier import ensure_startup_dossier
from skills.dataset_maintenance.startup_dossiers import migrate_startup_dossiers
from skills.dataset_maintenance.insight_manifests import migrate_insight_manifests

logger = get_logger(__name__)
app = typer.Typer(
    add_completion=False,
    help="Dataset storage and Qdrant maintenance.",
)


def _parse_datasets(dataset: str) -> list[str]:
    return [item.strip() for item in dataset.split(",") if item.strip()]


@app.command()
def diagnose(
    embeddings: Optional[str] = typer.Option(None, "--embeddings", "-e"),
) -> None:
    items = run_command(
        lambda: diagnose_qdrant_collections(embeddings),
        logger=logger,
    )
    for item in items:
        typer.echo(f"{item.status}: {item.collection} ({item.dataset})")


@app.command()
def prune(
    embeddings: Optional[str] = typer.Option(None, "--embeddings", "-e"),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Delete orphaned dataset tenants. Default is dry-run.",
    ),
) -> None:
    collections = run_command(
        lambda: prune_orphaned_qdrant_collections(
            embeddings,
            apply=apply,
        ),
        logger=logger,
    )
    action = "Deleted" if apply else "Would delete"
    for collection in collections:
        typer.echo(f"{action}: {collection}")


@app.command("delete")
def delete_command(
    dataset: Optional[str] = typer.Option(None, "--dataset", "-d"),
    embeddings: Optional[str] = typer.Option(None, "--embeddings", "-e"),
) -> None:
    collections = run_command(
        lambda: delete_dataset_index(dataset, embeddings),
        logger=logger,
    )
    for collection in collections:
        typer.echo(f"Deleted: {collection}")


@app.command("rebuild-index")
def rebuild_index_command(
    dataset: str = typer.Option(..., "--dataset", "-d"),
    sync: bool = typer.Option(
        True,
        "--sync/--no-sync",
        help="Re-index immediately after removing the dataset tenant.",
    ),
) -> None:
    """Recreate a dataset index so it gains BM25 vectors for hybrid search."""
    rebuilds = run_command(
        lambda: [
            rebuild_dataset_index(item)
            for item in _parse_datasets(dataset)
        ],
        logger=logger,
        error_prefix="Rebuild failed",
    )
    for rebuild in rebuilds:
        typer.echo(
            f"Reset: {rebuild.dataset} (collection={rebuild.collection}, "
            f"deleted={rebuild.collection_deleted}, "
            f"documents={rebuild.documents_reset})"
        )
    if not sync:
        typer.echo("Skipped re-indexing. Run a sync to rebuild the index.")
        return
    run_command(
        lambda: sync_datasets(
            [rebuild.dataset for rebuild in rebuilds],
            raise_on_error=True,
        ),
        logger=logger,
        error_prefix="Rebuild sync failed",
    )
    for rebuild in rebuilds:
        typer.echo(f"Rebuilt index: {rebuild.dataset}")


@app.command("activate")
def activate_command(
    dataset: str = typer.Option(..., "--dataset", "-d"),
) -> None:
    slugs = run_command(
        lambda: [activate_dataset_marker(item) for item in _parse_datasets(dataset)],
        logger=logger,
    )
    for slug in slugs:
        typer.echo(f"Activated: {slug}")


@app.command("archive")
def archive_command(
    dataset: str = typer.Option(..., "--dataset", "-d"),
) -> None:
    slugs = run_command(
        lambda: [archive_dataset_marker(item) for item in _parse_datasets(dataset)],
        logger=logger,
    )
    for slug in slugs:
        typer.echo(f"Archived: {slug}")


@app.command("create")
def create_command(
    startup_name: str = typer.Argument(..., help="Startup name for the new dossier."),
) -> None:
    slug = run_command(
        lambda: ensure_startup_dossier(startup_name),
        logger=logger,
        error_prefix="Create failed",
    )
    typer.echo(f"Created startup dossier: {slug}")


@app.command("migrate-startup-dossiers")
def migrate_startup_dossiers_command(
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Apply the migration. Default is dry-run.",
    ),
    manifest: str = typer.Option(
        "startup-dossier-migration.json",
        "--manifest",
    ),
) -> None:
    result = run_command(
        lambda: migrate_startup_dossiers(
            apply=apply,
            manifest_path=manifest,
        ),
        logger=logger,
    )
    typer.echo(
        f"actions={sum(result['counts'].values())} "
        f"conflicts={len(result['conflicts'])} "
        f"manifest={result['manifest']}"
    )
    if result["conflicts"]:
        raise typer.Exit(code=1)


@app.command("migrate-insight-manifests")
def migrate_insight_manifests_command(
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Adopt reconstructable insight files. Default is dry-run.",
    ),
) -> None:
    result = run_command(
        lambda: migrate_insight_manifests(apply=apply),
        logger=logger,
    )
    typer.echo(
        f"candidates={result.candidates} adopted={result.adopted} "
        f"manual={result.manual} skipped={result.skipped}"
    )
    for reason, count in sorted(result.skipped_by_reason.items()):
        typer.echo(f"  {reason}: {count}")


@app.command("dataset-from-insight")
def dataset_from_insight_command(
    target_dataset: str = typer.Option(
        ...,
        "--target-dataset",
        help="Generated dataset to reconcile.",
    ),
    source_datasets: Optional[str] = typer.Option(
        None,
        "--source-datasets",
        "--source-dataset",
        help="Comma-separated source datasets. Omit to search all.",
    ),
    skill: str = typer.Option(
        ...,
        "--skill",
        help="Insight skill to collect, e.g. person_profile.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Report what would change without writing files.",
    ),
) -> None:
    selected = run_command(
        lambda: dataset_from_insight(
            target_dataset,
            _parse_datasets(source_datasets)
            if source_datasets is not None
            else None,
            skill,
            dry_run=dry_run,
        ),
        logger=logger,
        error_prefix="Dataset-from-insight failed",
    )
    typer.echo(f"Selected insights: {len(selected)}")
    for insight in selected:
        typer.echo(insight.path)


if __name__ == "__main__":
    app()
