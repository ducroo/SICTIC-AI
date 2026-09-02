"""Inspect and manually reconcile outstanding LinkedIn profiles."""

from __future__ import annotations

import json
from pathlib import Path

from lib.datasets.paths import dataset_location
from lib.infrastructure.logging import get_logger
from lib.people.linkedin.identity import (
    extract_linkedin_id,
    linkedin_profile_not_found,
)
from lib.people.linkedin.registry import (
    STATUS_FAILED,
    STATUS_NOT_FOUND,
    LinkedInRegistry,
)
from lib.people.linkedin.store import LinkedInProfileStore
from lib.storage import get_storage

logger = get_logger(__name__)


def diagnose_registry() -> list[dict]:
    diagnostics = []
    storage = get_storage()
    for key, entry in LinkedInRegistry().load().items():
        linkedin_id = entry.get("linkedin_id", "")
        missing_datasets = []
        stored_datasets = []
        for dataset in entry.get("datasets", []):
            try:
                location = dataset_location(dataset)
            except FileNotFoundError:
                missing_datasets.append(dataset)
                continue
            profile_path = f"{location.raw_rel}/linkedin/{linkedin_id}.json"
            if linkedin_id and storage.exists(profile_path):
                stored_datasets.append(dataset)
        diagnostics.append(
            {
                "registry_key": key,
                **entry,
                "missing_datasets": missing_datasets,
                "cached_datasets": stored_datasets,
            }
        )
    return diagnostics


def import_profiles(
    file_path: str,
    dataset: str | None = None,
    *,
    registry: LinkedInRegistry | None = None,
    storage=None,
) -> int:
    """Store manually retrieved profiles and reconcile their registry entries."""
    try:
        payload = json.loads(Path(file_path).read_text(encoding="utf-8"))
    except Exception as error:
        raise RuntimeError(
            f"Failed to read LinkedIn import file {file_path}: {error}"
        ) from error
    profiles = payload if isinstance(payload, list) else [payload]
    registry = registry or LinkedInRegistry()
    storage = storage or get_storage()
    imported = 0

    for profile in profiles:
        if not isinstance(profile, dict):
            logger.warning("Skipping imported LinkedIn value that is not an object")
            continue
        linkedin_id = extract_linkedin_id(
            profile.get("url", "")
            or profile.get("linkedinUrl", "")
            or profile.get("publicIdentifier", "")
            or profile.get("linkedin_id", "")
        )
        if linkedin_profile_not_found(profile):
            if linkedin_id:
                registry.mark_status(linkedin_id, STATUS_NOT_FOUND)
            continue
        if profile.get("error"):
            if linkedin_id:
                registry.mark_status(linkedin_id, STATUS_FAILED)
            continue
        if not linkedin_id:
            logger.warning("Skipping imported LinkedIn profile without an identifier")
            continue

        registered = registry.find(linkedin_id, linkedin_id)
        target_datasets = list(
            registered[1].get("datasets", []) if registered else []
        )
        if dataset:
            target_dataset = dataset_location(dataset).slug
            if target_dataset not in target_datasets:
                target_datasets.append(target_dataset)
        if not target_datasets:
            logger.warning(
                "Cannot import LinkedIn profile %s without a target dataset",
                linkedin_id,
            )
            continue
        for target_dataset in target_datasets:
            location = dataset_location(target_dataset)
            LinkedInProfileStore(
                storage,
                f"{location.raw_rel}/linkedin",
            ).write(linkedin_id, profile)
        registry.remove_identity(linkedin_id)
        imported += 1
    return imported
