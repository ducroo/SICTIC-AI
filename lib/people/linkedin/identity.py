"""LinkedIn identity normalization and result classification."""

from __future__ import annotations

import re
import unicodedata

from lib.linkedin_ids import normalize_linkedin_id
from lib.slugify import slugify


PROFILE_URL = re.compile(
    r"(?<![\w.-])(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/(?:in|pub)/[\w%\-]+",
    re.IGNORECASE,
)


def sanitize_name(name: str) -> str:
    if not name:
        return ""
    clean = "".join(character for character in name
                    if not unicodedata.category(character).startswith(("So", "C")))
    return re.sub(r"\s+", " ", clean).strip()


def profile_full_name(payload: dict) -> str:
    """Extract the structured profile name using the resolver's name policy."""
    raw_name = str(payload.get("fullName") or "").strip()
    if not raw_name:
        raw_name = " ".join(str(value).strip() for value in
                            (payload.get("firstName", ""), payload.get("lastName", "")) if value)
    return sanitize_name(raw_name) or raw_name


def profile_linkedin_id(payload: dict) -> str:
    source = (payload.get("publicIdentifier", "") or payload.get("url", "")
              or payload.get("linkedinUrl", "") or payload.get("inputUrl", "")
              or payload.get("linkedin_id", ""))
    return extract_linkedin_id(source)


def extract_linkedin_ids(text: str) -> list[str]:
    """Extract explicit personal profile URLs, excluding company URLs."""
    return list(dict.fromkeys(extract_linkedin_id(match.group()) for match in PROFILE_URL.finditer(text)))


def is_linkedin_document(filename: str) -> bool:
    """Recognize profiles in the dataset's canonical LinkedIn source directory."""
    return filename.replace("\\", "/").startswith("linkedin/")


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
