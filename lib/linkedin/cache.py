from __future__ import annotations

import json

from lib.logger import get_logger
from lib.people.model import Person, extract_email_addresses
from lib.linkedin.identity import sanitize_name

logger = get_logger(__name__)


class LinkedInCache:
    def __init__(self, storage, cache_rel: str):
        self.storage = storage
        self.cache_rel = cache_rel

    def load_all(self) -> dict[str, Person]:
        if not self.storage.exists(self.cache_rel):
            return {}
        people = {}
        for filename in self.storage.list(self.cache_rel, suffix=".json"):
            try:
                payload = json.loads(
                    self.storage.read_text(f"{self.cache_rel}/{filename}")
                )
            except Exception as exc:
                logger.warning(
                    "Ignoring invalid LinkedIn cache file %s: %s",
                    filename,
                    exc,
                )
                continue
            linkedin_id = filename.removesuffix(".json").lower()
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
            people[linkedin_id] = Person(
                full_name=sanitize_name(raw_name) or raw_name,
                linkedin_id=linkedin_id,
                email_addresses=extract_email_addresses(payload),
                linkedin_profile=payload,
            )
        return people

    def write(self, linkedin_id: str, payload: dict) -> None:
        if not linkedin_id:
            raise ValueError("LinkedIn cache writes require a canonical LinkedIn ID")
        self.storage.mkdir(self.cache_rel)
        self.storage.write_text(
            f"{self.cache_rel}/{linkedin_id.lower()}.json",
            json.dumps(payload, indent=2),
        )
