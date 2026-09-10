"""LinkedIn profile retrieval and outstanding-profile workflow."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable

from rapidfuzz import fuzz

from lib.datasets.paths import dataset_location, dataset_raw_path
from lib.infrastructure.apify import ApifyAdapter
from lib.infrastructure.errors import InfrastructureError, InfrastructureErrorKind
from lib.infrastructure.logging import get_logger
from lib.people.linkedin.identity import (
    extract_linkedin_id,
    linkedin_profile_not_found,
)
from lib.people.linkedin.registry import (
    KNOWN_STATUSES,
    STATUS_FAILED,
    STATUS_NOT_FOUND,
    STATUS_OPEN,
    LinkedInRegistry,
)
from lib.people.linkedin.store import LinkedInProfileStore
from lib.people.model import Person, extract_email_addresses
from lib.storage import get_storage

logger = get_logger(__name__)
LINKEDIN_PROFILE_ACTOR = "dev_fusion/Linkedin-Profile-Scraper"
_TERMINAL_RUN_STATUSES = {"SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"}


def sanitize_name(name: str) -> str:
    if not name:
        return ""
    clean = "".join(
        character
        for character in name
        if not unicodedata.category(character).startswith(("So", "C"))
    )
    return re.sub(r"\s+", " ", clean).strip()


def find_cached_person(
    person: Person,
    cached: list[Person],
    *,
    fuzzy_threshold: int = 90,
) -> Person | None:
    """Resolve a stored profile without crossing an explicit identity boundary."""
    if person.linkedin_id:
        return next(
            (
                candidate
                for candidate in cached
                if candidate.linkedin_id == person.linkedin_id
            ),
            None,
        )
    if person.email_addresses:
        requested = set(person.email_addresses)
        matches = [
            candidate
            for candidate in cached
            if requested & set(candidate.email_addresses)
        ]
        if len(matches) == 1:
            return matches[0]
    requested_name = sanitize_name(person.full_name)
    if not requested_name:
        return None
    scored = [
        (
            fuzz.token_sort_ratio(
                requested_name.casefold(),
                sanitize_name(candidate.full_name).casefold(),
            ),
            candidate,
        )
        for candidate in cached
        if candidate.full_name
    ]
    if not scored:
        return None
    score, candidate = max(scored, key=lambda item: item[0])
    return candidate if score >= fuzzy_threshold else None


def _person_from_payload(linkedin_id: str, payload: dict) -> Person:
    raw_name = str(payload.get("fullName") or "").strip()
    if not raw_name:
        raw_name = " ".join(
            str(value).strip()
            for value in (
                payload.get("firstName", ""),
                payload.get("lastName", ""),
            )
            if value
        )
    return Person(
        full_name=sanitize_name(raw_name) or raw_name,
        linkedin_id=linkedin_id,
        email_addresses=extract_email_addresses(payload),
        linkedin_profile=payload,
    )


class LinkedInResolver:
    """Retrieve LinkedIn profiles and maintain their outstanding-profile state."""

    def __init__(
        self,
        dataset_name: str,
        *,
        storage=None,
        registry: LinkedInRegistry | None = None,
        apify_factory: Callable[[], ApifyAdapter] = ApifyAdapter,
        wait_seconds: int = 60,
    ):
        location = dataset_location(dataset_name)
        self.dataset_name = location.slug
        self.storage = storage or get_storage()
        self.profile_store = LinkedInProfileStore(
            self.storage,
            f"{dataset_raw_path(self.dataset_name)}/linkedin",
        )
        self.registry = registry or LinkedInRegistry()
        self._apify_factory = apify_factory
        self.wait_seconds = wait_seconds
        self.profiles = self.profile_store.load_all()

    def get_cached_persons(self) -> list[Person]:
        return [
            _person_from_payload(linkedin_id, payload)
            for linkedin_id, payload in self.profiles.items()
        ]

    def get_all_persons(self) -> list[str]:
        return sorted(
            person.display_name
            for person in self.get_cached_persons()
            if person.display_name
        )

    def _store_profile(self, payload: dict, datasets: list[str]) -> str | None:
        linkedin_id = self._payload_linkedin_id(payload)
        if not linkedin_id:
            return None
        stored_profile = payload
        for dataset in datasets:
            stored_profile = LinkedInProfileStore(
                self.storage,
                f"{dataset_raw_path(dataset)}/linkedin",
            ).write(linkedin_id, payload)
        if self.dataset_name in datasets:
            self.profiles[linkedin_id] = stored_profile
        return linkedin_id

    @staticmethod
    def _payload_linkedin_id(payload: dict) -> str:
        source = (
            payload.get("publicIdentifier", "")
            or payload.get("url", "")
            or payload.get("linkedinUrl", "")
            or payload.get("inputUrl", "")
            or payload.get("linkedin_id", "")
        )
        return extract_linkedin_id(source)

    def _reconcile_run(
        self,
        apify: ApifyAdapter,
        run_id: str,
        entries: dict[str, dict],
        payloads: list[dict],
    ) -> None:
        run_entries = {
            key: entry
            for key, entry in entries.items()
            if entry.get("status") == run_id
        }
        resolved: set[str] = set()
        not_found: set[str] = set()
        failed: set[str] = set()
        for payload in payloads:
            linkedin_id = self._payload_linkedin_id(payload)
            if linkedin_id not in run_entries:
                continue
            if linkedin_profile_not_found(payload):
                not_found.add(linkedin_id)
                continue
            if payload.get("error"):
                failed.add(linkedin_id)
                continue
            stored_id = self._store_profile(
                payload,
                list(run_entries[linkedin_id].get("datasets", [])),
            )
            if stored_id:
                resolved.add(linkedin_id)

        for linkedin_id in resolved:
            self.registry.remove_identity(linkedin_id)
        self.registry.set_status(sorted(not_found), STATUS_NOT_FOUND)
        failed.update(set(run_entries) - resolved - not_found)
        self.registry.set_status(sorted(failed), STATUS_FAILED)
        apify.delete_run(run_id)

    def _process_outstanding_profiles(self) -> None:
        entries = self.registry.load()
        open_ids = sorted(
            entry["linkedin_id"]
            for entry in entries.values()
            if entry.get("status") == STATUS_OPEN and entry.get("linkedin_id")
        )
        run_ids = {
            str(entry.get("status"))
            for entry in entries.values()
            if entry.get("status") not in KNOWN_STATUSES
        }
        if not open_ids and not run_ids:
            return
        try:
            apify = self._apify_factory()
        except Exception as error:
            logger.error("Could not initialize Apify: %s", error)
            self.registry.set_status(open_ids, STATUS_FAILED)
            return

        if open_ids:
            urls = [
                f"https://www.linkedin.com/in/{linkedin_id}/"
                for linkedin_id in open_ids
            ]
            logger.info("Submitting LinkedIn batch for %d profiles", len(urls))
            try:
                new_run_id = apify.start_actor(
                    actor_id=LINKEDIN_PROFILE_ACTOR,
                    run_input={"profileUrls": urls},
                )
            except Exception as error:
                logger.error("Apify refused LinkedIn batch: %s", error)
                self.registry.set_status(open_ids, STATUS_FAILED)
                return
            self.registry.set_status(open_ids, new_run_id)
            run_ids.add(new_run_id)
            try:
                apify.wait_for_run(new_run_id, self.wait_seconds)
            except Exception as error:
                logger.warning("Could not wait for Apify run %s: %s", new_run_id, error)

        entries = self.registry.load()
        for run_id in sorted(run_ids):
            try:
                run = apify.get_run(run_id)
            except Exception as error:
                logger.warning("Could not inspect Apify run %s: %s", run_id, error)
                continue
            status = str(run.get("status") or "")
            if status not in _TERMINAL_RUN_STATUSES:
                continue
            run_linkedin_ids = [
                entry["linkedin_id"]
                for entry in entries.values()
                if entry.get("status") == run_id
            ]
            if status != "SUCCEEDED":
                self.registry.set_status(run_linkedin_ids, STATUS_FAILED)
                apify.delete_run(run_id)
                continue
            try:
                payloads = apify.run_items(run)
            except Exception as error:
                logger.warning(
                    "Could not retrieve results for Apify run %s: %s",
                    run_id,
                    error,
                )
                continue
            self._reconcile_run(apify, run_id, entries, payloads)

    def _register_profiles(self, persons: list[Person]) -> set[str]:
        requested_ids: set[str] = set()
        for person in persons:
            linkedin_id = extract_linkedin_id(person.linkedin_id)
            if not linkedin_id:
                continue
            requested_ids.add(linkedin_id)
            if linkedin_id in self.profiles:
                self.registry.remove_identity(linkedin_id)
                continue
            registered = self.registry.find(
                linkedin_id,
                linkedin_id,
                person.full_name,
            )
            status = registered[1].get("status", STATUS_OPEN) if registered else STATUS_OPEN
            self.registry.upsert(
                linkedin_id,
                dataset=self.dataset_name,
                full_name=person.full_name,
                linkedin_id=linkedin_id,
                status=status,
            )
        return requested_ids

    def _raise_for_unresolved(self, requested_ids: set[str]) -> None:
        entries = self.registry.load()
        failed = []
        pending = []
        for linkedin_id in requested_ids:
            entry = entries.get(linkedin_id)
            if not entry:
                continue
            status = entry.get("status")
            if status == STATUS_FAILED:
                failed.append(linkedin_id)
            elif status != STATUS_NOT_FOUND:
                pending.append(linkedin_id)
        if failed:
            raise InfrastructureError(
                "LinkedIn profiles require manual retrieval: "
                + ", ".join(sorted(failed)),
                kind=InfrastructureErrorKind.SERVICE_UNAVAILABLE,
                provider="linkedin",
                operation="get_profiles",
                recoverable=True,
            )
        if pending:
            raise InfrastructureError(
                "LinkedIn profiles are still being processed: "
                + ", ".join(sorted(pending)),
                kind=InfrastructureErrorKind.RESOURCE_BUSY,
                provider="linkedin",
                operation="get_profiles",
            )

    def get_profiles(
        self,
        person_list: list[Person],
        allow_scrape: bool = True,
    ) -> list[Person]:
        """Return the supplied people enriched with available LinkedIn profiles."""
        cached = self.get_cached_persons()
        outstanding: list[Person] = []
        for person in person_list:
            cleaned_name = sanitize_name(person.full_name)
            if cleaned_name:
                person.full_name = cleaned_name
            match = find_cached_person(person, cached)
            if match is not None:
                person.merge(match)
            elif person.linkedin_id:
                outstanding.append(person)

        if not outstanding:
            return person_list
        requested_ids = self._register_profiles(outstanding)
        if not allow_scrape:
            return person_list

        self._process_outstanding_profiles()
        self.profiles.update(self.profile_store.load_all())
        self._raise_for_unresolved(requested_ids)
        resolved = [
            _person_from_payload(linkedin_id, self.profiles[linkedin_id])
            for linkedin_id in requested_ids
            if linkedin_id in self.profiles
        ]
        for person in person_list:
            match = find_cached_person(person, resolved)
            if match is not None:
                person.merge(match)
        return person_list
