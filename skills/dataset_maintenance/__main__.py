from __future__ import annotations

from typing import Optional

import typer

from lib.cli import run_command
from lib.insights import hydrate_dataset_from_insights
from lib.logger import get_logger
from skills.dataset_maintenance.dataset_from_insight import (
    print_hydration_result,
)
from skills.dataset_maintenance.maintenance import (
    delete_dataset_index,
    diagnose_qdrant_collections,
    prune_orphaned_qdrant_collections,
)
from skills.dataset_maintenance.startup_dossiers import migrate_startup_dossiers
from skills.dataset_maintenance.insight_manifests import migrate_insight_manifests

logger = get_logger(__name__)
app = typer.Typer(
    add_completion=False,
    help="Dataset storage and Qdrant maintenance.",
)


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
        help="Delete orphaned collections. Default is dry-run.",
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


@app.command("from-insight")
def from_insight_command(
    insight_name: str = typer.Option(
        ...,
        "--insight-name",
        "--insight",
        help="Insight name to hydrate, e.g. person_profile.",
    ),
    source_dataset: Optional[str] = typer.Option(
        None,
        "--source-dataset",
        help="Optional source dataset whose insight folder should be scanned.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Report what would change without writing files.",
    ),
) -> None:
    result = run_command(
        lambda: hydrate_dataset_from_insights(
            insight_name=insight_name,
            source_dataset=source_dataset,
            dry_run=dry_run,
        ),
        logger=logger,
        error_prefix="Hydration failed",
    )
    print_hydration_result(result)


if __name__ == "__main__":
    app()
