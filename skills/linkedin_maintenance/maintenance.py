from __future__ import annotations

from lib.datasets.state import is_active_dataset
from lib.people.linkedin.registry import (
    STATUS_FAILED,
    STATUS_OPEN,
    LinkedInRegistry,
)
from lib.people.linkedin.maintenance import (
    diagnose_registry,
    import_profiles,
)
from lib.infrastructure.logging import get_logger
from lib.datasets.paths import list_all_dataset_names
from lib.people.discovery import persons_in_dataset
from lib.people.linkedin import LinkedInResolver

logger = get_logger(__name__)
ACTIONABLE_STATUSES = {STATUS_OPEN, STATUS_FAILED}


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
