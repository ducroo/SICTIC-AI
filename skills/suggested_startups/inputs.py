"""Resolve canonical inputs and stored profile insights for the skill."""

from __future__ import annotations

from dataclasses import dataclass

from lib.insights import InsightFile, select_insights
from lib.linkedin_ids import normalize_linkedin_id
from lib.infrastructure.logging import get_logger
from lib.people.discovery import persons_in_dataset
from lib.people.model import Person
from lib.slugify import slugify
from lib.infrastructure.configuration import config_cache_key

logger = get_logger(__name__)

STARTUP_PROFILES_DATASET = "available-startup-profiles"


@dataclass(frozen=True)
class SuggestedStartupsConfig:
    prompt: str
    key: str


@dataclass(frozen=True)
class SuggestedStartupsRequest:
    dataset: str
    startups: list[str]
    investors: list[Person]
    max_startups: int


def load_skill_config(config: dict) -> SuggestedStartupsConfig:
    try:
        section = config["suggested_startups"]
        prompt = section["suggested_startups_prompt"]
        ranking_top_k = config["ranking_top_k"]
        ranking_rationale = config["ranking_rationale"]
        structured_output = config["structured_output"]
    except KeyError as error:
        raise ValueError(
            f"Missing configuration for suggested_startups: {error}"
        ) from error
    if not isinstance(prompt, str):
        raise ValueError(
            "suggested_startups requires a Markdown objective prompt."
        )
    return SuggestedStartupsConfig(
        prompt=prompt,
        key=config_cache_key(
            section,
            ranking_top_k,
            ranking_rationale,
            structured_output,
        ),
    )


def resolve_request(
    dataset_name: str,
    startups: list[str] | None,
    investors: list[str] | None,
    max_startups: int,
    *,
    config: dict,
    available_startups: list[str],
) -> SuggestedStartupsRequest:
    if max_startups < 1:
        raise ValueError("max_startups must be at least 1.")

    dataset = slugify(dataset_name)
    resolved_startups = _resolve_startups(
        startups,
        config,
        available_startups,
    )
    resolved_investors = _resolve_investors(dataset, investors)
    if not resolved_startups or not resolved_investors:
        raise ValueError(
            "Startups and investors lists cannot be empty after default "
            "resolution."
        )
    return SuggestedStartupsRequest(
        dataset=dataset,
        startups=resolved_startups,
        investors=resolved_investors,
        max_startups=max_startups,
    )


def _resolve_startups(
    requested: list[str] | None,
    config: dict,
    available: list[str],
) -> list[str]:
    if requested:
        return list(dict.fromkeys(slugify(item) for item in requested))

    bulk_config = config.get("bulk_refresh", {})
    excluded = {
        slugify(item)
        for key, fallback in (
            ("community_datasets", ["sictic-members"]),
            ("ignore_datasets", ["investor-profile", "person-profile"]),
        )
        for item in bulk_config.get(key, fallback)
    }
    return [
        slugify(item)
        for item in available
        if slugify(item) not in excluded
    ]


def _resolve_investors(
    dataset: str,
    requested: list[str] | None,
) -> list[Person]:
    roster = persons_in_dataset(dataset)
    if not requested:
        incomplete = [
            person.display_name
            for person in roster
            if not person.linkedin_id and person.display_name
        ]
        if incomplete:
            logger.warning(
                "[%s] Skipping %d persons without a LinkedIn ID from the "
                "suggested-startups roster.",
                dataset,
                len(incomplete),
            )
        return [
            person
            for person in roster
            if person.linkedin_id and person.display_name
        ]

    by_linkedin_id = {
        person.linkedin_id: person
        for person in roster
        if person.linkedin_id
    }
    resolved: list[Person] = []
    missing: list[str] = []
    seen: set[str] = set()
    for value in requested:
        candidate = by_linkedin_id.get(normalize_linkedin_id(value))
        if candidate is None:
            candidate = Person(full_name=value).find_best_match(roster)
        if candidate is None or not candidate.linkedin_id:
            missing.append(value)
            continue
        if candidate.linkedin_id not in seen:
            resolved.append(candidate)
            seen.add(candidate.linkedin_id)
    if missing:
        raise ValueError(
            "No canonical person with a LinkedIn ID found for: "
            + ", ".join(missing)
        )
    return resolved


async def load_startup_profiles(
    startups: list[str],
) -> list[InsightFile]:
    selected = select_insights(startups, "startup_profile")
    by_dataset: dict[str, InsightFile] = {}
    for profile in selected:
        dataset = slugify(profile.dataset)
        if dataset in by_dataset:
            raise ValueError(
                f"Multiple selected startup profiles found for '{dataset}'."
            )
        by_dataset[dataset] = profile
    missing = [startup for startup in startups if startup not in by_dataset]
    if missing:
        raise ValueError(
            "No stored startup profile available for: " + ", ".join(missing)
        )
    return [by_dataset[startup] for startup in startups]


def load_investor_profiles(
    dataset: str,
    investors: list[Person],
) -> dict[str, str]:
    profiles: dict[str, str] = {}
    missing: list[str] = []
    for person in investors:
        selected = InsightFile(
            dataset=dataset,
            skill="investor_profile",
            model="manual",
            identifier=person.linkedin_id,
            subdir=True,
        ).find(selection="any")
        if selected is None:
            missing.append(person.display_name)
            continue
        profiles[person.linkedin_id] = selected.content()
    if missing:
        raise ValueError(
            "No stored investor profile available for: " + ", ".join(missing)
        )
    return profiles
