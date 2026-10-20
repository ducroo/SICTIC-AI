"""Dated Dealum snapshot layout, migration and collection bookkeeping."""

import json
import os
import shutil
import uuid
from datetime import date
from pathlib import Path

from lib.infrastructure.filesystem import replace_directory_snapshot
from lib.infrastructure.logging import get_logger
from lib.insights.locking import atomic_write, write_if_changed
from lib.startups.dealum.manifest import (
    LAST_SUCCESSFUL_PULL_AT, MANIFEST_JSON, read_manifest, stable_json,
)
from lib.startups.dealum.matching import (
    DealumMatch, DealumReconciliationError, application_create_day,
)
from lib.storage import get_storage

logger = get_logger(__name__)


def stored_applications(dataset_slug: str, root: str) -> dict[str, dict]:
    storage = get_storage()
    stored = {}
    for name in storage.list(root):
        if not storage.is_dir(f"{root}/{name}"):
            continue
        try:
            if date.fromisoformat(name).isoformat() != name:
                continue
        except ValueError:
            continue
        manifest = read_manifest(dataset_slug, dealum_rel=f"{root}/{name}")
        if manifest.get("dealum_id") in (None, ""):
            raise DealumReconciliationError(f"Cannot identify existing Dealum folder {root}/{name}.")
        stored[name] = manifest
    return stored


def validate_application_paths(matches: list[DealumMatch], stored: dict[str, dict]) -> None:
    """Never overwrite another ID, or duplicate an ID after a date correction."""
    by_day = {day: str(item["dealum_id"]) for day, item in stored.items()}
    by_id = {}
    for day, identifier in by_day.items():
        if identifier in by_id:
            raise DealumReconciliationError(f"Dealum application {identifier} exists in multiple dated folders.")
        by_id[identifier] = day
    seen = set()
    for match in matches:
        day = application_create_day(match.application)
        if match.dealum_id in (None, ""):
            raise DealumReconciliationError("Dealum application is missing its ID.")
        identifier = str(match.dealum_id)
        if identifier in seen:
            raise DealumReconciliationError(f"Duplicate Dealum application ID {identifier} in API response.")
        seen.add(identifier)
        if day in by_day and by_day[day] != identifier:
            raise DealumReconciliationError(
                f"Dealum applications {by_day[day]} and {identifier} share createDate day {day}; cannot overwrite."
            )
        if identifier in by_id and by_id[identifier] != day:
            raise DealumReconciliationError(
                f"Dealum application {identifier} changed createDate from {by_id[identifier]} to {day}; reconcile folders first."
            )
        by_day[day] = identifier
        by_id[identifier] = day


def write_collection_manifest(dataset_slug: str, root: str, *, successful_pull: int | None) -> None:
    stored = stored_applications(dataset_slug, root)
    if not stored:
        return
    manifest = {"latest_application": max(stored)}
    if successful_pull is not None:
        manifest[LAST_SUCCESSFUL_PULL_AT] = successful_pull
    write_if_changed(get_storage(), f"{root}/{MANIFEST_JSON}", stable_json(manifest))


# TEMPORARY MIGRATION — review for removal after 2027-02-16.
# This function upgrades pre-2026-10-16 flat datasets/dealum/ snapshots to
# datasets/dealum/<createDate day>/ on their next import. Before removing it,
# verify that flat snapshots are gone on all installations, including archived
# dossiers that may not have been imported recently. Remove the whole function,
# its migration-only imports, and its caller/import/migrated flag in importing.py
# together with the migration-specific tests in test_dealum_import.py.
# The dated-folder validation and collection bookkeeping above are permanent.
def migrate_flat_snapshot(dataset_slug: str, root: str, matches: list[DealumMatch]) -> bool:
    """Atomically nest a legacy snapshot, retaining bytes, mtimes and its identity."""
    storage = get_storage()
    raw_path = f"{root}/application.raw.json"
    if not storage.exists(raw_path):
        if any(storage.exists(f"{root}/{name}") for name in ("application.md", "application.md.txt", "documents")):
            raise DealumReconciliationError(f"Cannot migrate {root}: missing application.raw.json.")
        return False
    application = json.loads(storage.read_text(raw_path))
    day = application_create_day(application)
    previous = read_manifest(dataset_slug, dealum_rel=root)
    identifier = application.get("id")
    if identifier in (None, "") or str(previous.get("dealum_id")) != str(identifier):
        raise DealumReconciliationError(f"Cannot migrate {root}: application ID and manifest disagree.")
    if stored_applications(dataset_slug, root):
        raise DealumReconciliationError(f"Cannot migrate {root}: mixed flat and dated snapshots.")
    validate_application_paths(matches, {day: previous})

    target = Path(storage.local_path(root))
    staging = target.with_name(f".dealum-migration-{uuid.uuid4().hex}")
    try:
        # Hard links preserve source bytes and timestamps without duplicating downloads.
        shutil.copytree(target, staging / day, copy_function=os.link)
        migrated = dict(previous)
        migrated["files"] = [
            {**item, "path": f"{root}/{day}/documents/{item['filename']}"}
            for item in previous.get("files", [])
        ]
        # Replace this hard link, rather than writing through it to the live manifest.
        atomic_write(staging / day / MANIFEST_JSON, stable_json(migrated))
        atomic_write(staging / MANIFEST_JSON, stable_json({"latest_application": day}))
        replace_directory_snapshot(staging, target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    logger.info("[%s] Migrated flat Dealum application %s into %s/%s", dataset_slug, identifier, root, day)
    return True
