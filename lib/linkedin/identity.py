from __future__ import annotations

import re
import unicodedata

from rapidfuzz import fuzz

from lib.people.model import Person
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
    return match.group(1).lower() if match else slugify(clean)


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
    """Resolve a cache match without crossing an explicit identity boundary."""
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
        email_matches = [
            candidate
            for candidate in cached
            if requested & set(candidate.email_addresses)
        ]
        if len(email_matches) == 1:
            return email_matches[0]

    requested_name = sanitize_name(person.full_name)
    if not requested_name:
        return None

    scored = [
        (
            fuzz.token_sort_ratio(
                requested_name.lower(),
                sanitize_name(candidate.full_name).lower(),
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


def unresolved_registry_key(person: Person) -> str:
    if person.linkedin_id:
        return person.linkedin_id
    if person.email_addresses:
        return f"email:{person.email_addresses[0]}"
    return f"name:{slugify(sanitize_name(person.full_name))}"
