"""LinkedIn identity normalization and result classification."""

from __future__ import annotations

import re

from lib.linkedin_ids import normalize_linkedin_id
from lib.slugify import slugify


def extract_linkedin_id(value: str) -> str:
    if not value:
        return ""
    clean = value.split("?", 1)[0].strip().strip("/")
    match = re.search(
        r"linkedin\.com/(?:in|pub)/([^/]+)",
        clean,
        re.IGNORECASE,
    )
    identifier = match.group(1).lower() if match else slugify(clean)
    return normalize_linkedin_id(identifier)


def linkedin_profile_not_found(payload: dict) -> bool:
    """Return true only when a result explicitly says the profile is absent."""
    if payload.get("not_found") is True:
        return True
    status_code = payload.get("statusCode") or payload.get("status_code")
    if status_code == 404:
        return True
    error = str(payload.get("error") or "").casefold()
    return any(marker in error for marker in ("not found", "does not exist"))
