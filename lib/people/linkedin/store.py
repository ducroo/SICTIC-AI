"""Persistence for raw LinkedIn profile responses."""

from __future__ import annotations

import json

from lib.infrastructure.logging import get_logger
from lib.linkedin_ids import normalize_linkedin_id
from lib.people.linkedin.cleaning import clean_linkedin_payload

logger = get_logger(__name__)


class LinkedInProfileStore:
    def __init__(self, storage, profile_path: str):
        self.storage = storage
        self.profile_path = profile_path

    def load_all(self) -> dict[str, dict]:
        if not self.storage.exists(self.profile_path):
            return {}
        profiles = {}
        for filename in self.storage.list(self.profile_path, suffix=".json"):
            try:
                payload = json.loads(
                    self.storage.read_text(f"{self.profile_path}/{filename}")
                )
            except Exception as error:
                logger.warning(
                    "Ignoring invalid LinkedIn profile file %s: %s",
                    filename,
                    error,
                )
                continue
            if not isinstance(payload, dict):
                logger.warning(
                    "Ignoring LinkedIn profile %s: JSON value is not an object",
                    filename,
                )
                continue
            linkedin_id = normalize_linkedin_id(filename.removesuffix(".json"))
            profiles[linkedin_id] = payload
        return profiles

    def write(self, linkedin_id: str, payload: dict) -> dict:
        if not linkedin_id:
            raise ValueError("LinkedIn profile writes require a LinkedIn ID")
        cleaned = clean_linkedin_payload(payload)
        self.storage.mkdir(self.profile_path)
        self.storage.write_text(
            f"{self.profile_path}/{normalize_linkedin_id(linkedin_id)}.json",
            json.dumps(cleaned, indent=2),
        )
        return cleaned
