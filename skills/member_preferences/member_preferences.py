"""Member communication preferences.

The Google Sheet adapter will replace the default assignment below once its
schema and credentials are configured. Keeping this as a separate routine
lets callers decide which skill-specific preference applies.
"""

from __future__ import annotations

from lib.infrastructure.logging import get_logger
from lib.people import Person
from lib.people.discovery import persons_in_dataset

logger = get_logger(__name__)

PREFERENCES_ADHOC_TAG = "member_preferences"


def preferences_for(person: Person) -> dict[str, object]:
    """Return this person's preferences without creating ad-hoc data."""
    return person.adhoc_data.get(PREFERENCES_ADHOC_TAG, {})


def member_preferences(dataset_name: str = "sictic-members") -> list[Person]:
    """Return the complete member roster with all known preferences attached."""
    people = persons_in_dataset(dataset_name)
    for person in people:
        person.adhoc_data.setdefault(PREFERENCES_ADHOC_TAG, {}).setdefault(
            "deep_dive_invitation",
            "standard",
        )
    logger.info(
        "[%s] Loaded %d members with default invitation preferences.",
        dataset_name,
        len(people),
    )
    return people


def render_member_preferences(people: list[Person]) -> str:
    """Render the roster in the same person-table shape used elsewhere."""
    lines = [
        "| full-name | linkedin-id | email-addresses | preferences |",
        "|---|---|---|---|",
    ]
    for person in people:
        preferences = ", ".join(
            f"{key}={value}" for key, value in sorted(preferences_for(person).items())
        )
        lines.append(
            f"| {person.full_name} | {person.linkedin_id} | "
            f"{', '.join(person.email_addresses)} | {preferences} |"
        )
    return "\n".join(lines) + "\n"
