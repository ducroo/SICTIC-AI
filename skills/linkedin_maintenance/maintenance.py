from __future__ import annotations

import json
from pathlib import Path

from lib.datasets.state import is_active_dataset
from lib.linkedin.cache import LinkedInCache
from lib.linkedin.identity import extract_linkedin_id
from lib.linkedin.payload import clean_linkedin_payload
from lib.linkedin.registry import LinkedInRegistry
from lib.linkedin.resolver import LinkedInResolver
from lib.logger import get_logger
from lib.storage import get_storage
from lib.datasets.paths import (
    dataset_location,
    dataset_raw_path,
    list_all_dataset_names,
)
from lib.people.discovery import persons_in_dataset

logger = get_logger(__name__)
ACTIONABLE_STATUSES = {"PENDING", "URL_NOT_FOUND", "SCRAPE_FAILED"}


def missing_profile_urls(entries: list[dict]) -> list[str]:
    """Return LinkedIn profile URLs for actionable missing-profile entries."""
    urls = []
    for entry in entries:
        linkedin_id = entry.get("linkedin_id", "").strip().strip("/")
        if not linkedin_id:
            continue
        urls.append(f"https://www.linkedin.com/in/{linkedin_id}/")
    return sorted(dict.fromkeys(urls))


def missing_profiles() -> list[dict]:
    for dataset in list_all_dataset_names(("startups", "community")):
        if not is_active_dataset(dataset):
            continue
        people = persons_in_dataset(dataset)
        if people:
            LinkedInResolver(dataset).get_profiles(
                people,
                allow_scrape=False,
            )
    return [
        {"registry_key": key, **entry}
        for key, entry in LinkedInRegistry().load().items()
        if entry.get("status") in ACTIONABLE_STATUSES
    ]


def diagnose_registry() -> list[dict]:
    diagnostics = []
    storage = get_storage()
    for key, entry in LinkedInRegistry().load().items():
        linkedin_id = entry.get("linkedin_id", "")
        datasets = entry.get("datasets", [])
        missing_datasets = []
        cached_datasets = []
        for dataset in datasets:
            try:
                dataset_location(dataset)
            except FileNotFoundError:
                missing_datasets.append(dataset)
                continue
            cache_rel = f"{dataset_raw_path(dataset)}/linkedin/{linkedin_id}.json"
            if linkedin_id and storage.exists(cache_rel):
                cached_datasets.append(dataset)
        diagnostics.append(
            {
                "registry_key": key,
                **entry,
                "missing_datasets": missing_datasets,
                "cached_datasets": cached_datasets,
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
    try:
        payload = json.loads(Path(file_path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(
            f"Failed to read LinkedIn import file {file_path}: {exc}"
        ) from exc
    profiles = payload if isinstance(payload, list) else [payload]
    registry = registry or LinkedInRegistry()
    storage = storage or get_storage()
    imported = 0

    for profile in profiles:
        identifier_source = (
            profile.get("url", "")
            or profile.get("linkedinUrl", "")
            or profile.get("publicIdentifier", "")
            or profile.get("linkedin_id", "")
        )
        linkedin_id = extract_linkedin_id(identifier_source)
        if profile.get("error") or profile.get("not_found"):
            if linkedin_id:
                registry.mark_status(linkedin_id, "DO_NOT_SCRAPE")
            continue
        if not linkedin_id:
            logger.warning(
                "Skipping imported LinkedIn profile without an identifier"
            )
            continue

        registered = registry.find(linkedin_id, linkedin_id)
        registry_entry = registered[1] if registered else {}
        target_datasets = list(registry_entry.get("datasets", []))
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

        cleaned = clean_linkedin_payload(profile)
        for target_dataset in target_datasets:
            location = dataset_location(target_dataset)
            cache = LinkedInCache(
                storage,
                f"{location.raw_rel}/linkedin",
            )
            cache.write(linkedin_id, cleaned)
            logger.info(
                "Imported LinkedIn profile %s into %s",
                linkedin_id,
                target_dataset,
            )
        registry.remove_identity(linkedin_id)
        imported += 1
    return imported
