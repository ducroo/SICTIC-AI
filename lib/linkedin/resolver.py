from __future__ import annotations

from collections.abc import Callable

from lib.adapters.apify import ApifyAdapter
from lib.adapters.web_search import WebSearchAdapter
from lib.linkedin.cache import LinkedInCache
from lib.linkedin.identity import (
    extract_linkedin_id,
    find_cached_person,
    sanitize_name,
    unresolved_registry_key,
)
from lib.linkedin.payload import clean_linkedin_payload
from lib.linkedin.registry import LinkedInRegistry
from lib.logger import get_logger
from lib.people.model import Person, extract_email_addresses
from lib.storage import get_storage
from lib.datasets.paths import dataset_location, dataset_raw_path

logger = get_logger(__name__)
LINKEDIN_PROFILE_ACTOR = "dev_fusion/Linkedin-Profile-Scraper"


class LinkedInResolver:
    """Resolve Person objects from cache, search, and optional LinkedIn scraping."""

    def __init__(
        self,
        dataset_name: str,
        *,
        storage=None,
        registry: LinkedInRegistry | None = None,
        web_search_factory: Callable[[], WebSearchAdapter] = WebSearchAdapter,
        apify_factory: Callable[[], ApifyAdapter] = ApifyAdapter,
    ):
        location = dataset_location(dataset_name)
        self.dataset_name = location.slug
        self.storage = storage or get_storage()
        self.cache_store = LinkedInCache(
            self.storage,
            f"{dataset_raw_path(self.dataset_name)}/linkedin",
        )
        self.registry_store = registry or LinkedInRegistry()
        self._web_search_factory = web_search_factory
        self._apify_factory = apify_factory
        self.cache = self.cache_store.load_all()

    def get_cached_persons(self) -> list[Person]:
        return list(self.cache.values())

    def get_all_persons(self) -> list[str]:
        return sorted(
            {
                person.display_name
                for person in self.cache.values()
                if person.display_name
            }
        )

    def _discover_linkedin_id(self, person: Person) -> str:
        query = f"{sanitize_name(person.full_name)} {self.dataset_name}"
        try:
            results = self._web_search_factory().search(
                f"{query} site:linkedin.com/in/"
            )
        except Exception as exc:
            logger.warning("LinkedIn web search failed for %s: %s", query, exc)
            return ""
        for result in results:
            url = result.get("link", "")
            if "linkedin.com/in/" in url.lower():
                return extract_linkedin_id(url)
        return ""

    def _cache_scraped_profile(self, payload: dict) -> Person | None:
        identifier_source = (
            payload.get("publicIdentifier", "")
            or payload.get("url", "")
            or payload.get("linkedinUrl", "")
        )
        linkedin_id = extract_linkedin_id(identifier_source)
        if not linkedin_id:
            return None
        cleaned = clean_linkedin_payload(payload)
        self.cache_store.write(linkedin_id, cleaned)
        raw_name = payload.get("fullName", "")
        if not raw_name:
            raw_name = " ".join(
                value
                for value in (
                    payload.get("firstName", ""),
                    payload.get("lastName", ""),
                )
                if value
            )
        person = Person(
            full_name=sanitize_name(raw_name) or raw_name,
            linkedin_id=linkedin_id,
            email_addresses=extract_email_addresses(cleaned),
            linkedin_profile=cleaned,
        )
        self.cache[linkedin_id] = person
        self.registry_store.remove_identity(linkedin_id)
        return person

    def get_profiles(
        self,
        person_list: list[Person],
        allow_scrape: bool = True,
    ) -> list[Person]:
        result: list[Person] = []
        scrape_ids: list[str] = []

        for person in person_list:
            sanitized_name = sanitize_name(person.full_name)
            if sanitized_name:
                person.full_name = sanitized_name

            cached = find_cached_person(person, list(self.cache.values()))
            if cached is not None:
                person.merge(cached)
                result.append(person)
                continue

            registry_key = unresolved_registry_key(person)
            registered = self.registry_store.find(
                registry_key,
                person.linkedin_id,
                person.full_name,
            )
            if registered:
                registered_key, registry_entry = registered
                self.registry_store.upsert(
                    registered_key,
                    dataset=self.dataset_name,
                    full_name=person.full_name,
                    linkedin_id=person.linkedin_id,
                    status=registry_entry.get("status", "PENDING"),
                )
                logger.info(
                    "Skipping automated scrape for %s: registry status=%s",
                    registry_key,
                    registry_entry.get("status"),
                )
                result.append(person)
                continue

            linkedin_id = person.linkedin_id
            if not linkedin_id:
                linkedin_id = self._discover_linkedin_id(person)
                if linkedin_id:
                    person.linkedin_id = linkedin_id
                    registry_key = linkedin_id
                else:
                    self.registry_store.upsert(
                        registry_key,
                        dataset=self.dataset_name,
                        full_name=person.full_name,
                        linkedin_id="",
                        status="URL_NOT_FOUND",
                    )
                    result.append(person)
                    continue

            self.registry_store.upsert(
                registry_key,
                dataset=self.dataset_name,
                full_name=person.full_name,
                linkedin_id=linkedin_id,
                status="PENDING",
            )
            scrape_ids.append(linkedin_id)
            result.append(person)

        if not scrape_ids or not allow_scrape:
            return result

        ordered_ids = list(dict.fromkeys(scrape_ids))
        urls = [
            f"https://www.linkedin.com/in/{linkedin_id}/"
            for linkedin_id in ordered_ids
        ]
        logger.info(
            "Initiating blocking batch scrape for %s profiles...",
            len(urls),
        )
        try:
            payloads = self._apify_factory().run_actor(
                actor_id=LINKEDIN_PROFILE_ACTOR,
                run_input={"profileUrls": urls},
            )
        except Exception as exc:
            logger.error("Apify LinkedIn batch scrape failed: %s", exc)
            for linkedin_id in ordered_ids:
                self.registry_store.mark_status(linkedin_id, "SCRAPE_FAILED")
            return result

        scraped_ids = set()
        for payload in payloads:
            cached_person = self._cache_scraped_profile(payload)
            if cached_person is None:
                continue
            scraped_ids.add(cached_person.linkedin_id)
            for person in result:
                if person.linkedin_id == cached_person.linkedin_id:
                    person.merge(cached_person)

        for linkedin_id in ordered_ids:
            if linkedin_id not in scraped_ids:
                self.registry_store.mark_status(linkedin_id, "SCRAPE_FAILED")
        return result
