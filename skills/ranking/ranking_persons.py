from typing import Any, List, Optional

from lib.insights import InsightFile, select_insights
from lib.infrastructure.logging import get_logger
from lib.people.discovery import persons_in_dataset
from lib.people.model import Person, normalize_email_addresses
from lib.slugify import slugify
from skills.ranking.ranking_rationale import ranking_rationale
from skills.ranking.ranking_top_k import ranking_top_k

logger = get_logger(__name__)


def _person_reference(value: str, members: List[Person]) -> Person:
    value = value.strip()
    emails = normalize_email_addresses(value)
    if emails:
        return Person(email_addresses=emails)

    normalized = slugify(value)
    exact_linkedin = next(
        (member for member in members if member.linkedin_id == normalized),
        None,
    )
    if exact_linkedin:
        return Person(linkedin_id=normalized)
    return Person(full_name=value)


def _resolve_person(
    value: str,
    members: List[Person],
    *,
    threshold: int = 85,
) -> Optional[Person]:
    reference = _person_reference(value, members)
    return reference.find_best_match(members, threshold=threshold)


def _resolve_members(
    members: List[Person],
    candidates: Optional[List[str]],
    optout: Optional[List[str]],
) -> List[Person]:
    if candidates:
        selected: List[Person] = []
        missing_candidates = []
        for value in candidates:
            matched = _resolve_person(value, members)
            if matched is None:
                missing_candidates.append(value)
            elif matched not in selected:
                selected.append(matched)

        if missing_candidates:
            message = (
                "The following requested candidates could not be matched to "
                f"sictic-members: {', '.join(missing_candidates)}"
            )
            logger.error(message)
            raise ValueError(message)
    else:
        selected = list(members)

    if optout:
        excluded_identifiers = set()
        missing_optouts = []
        for value in optout:
            matched = _resolve_person(value, members)
            if matched is None:
                missing_optouts.append(value)
            else:
                excluded_identifiers.add(matched.identifier)

        if missing_optouts:
            logger.warning(
                "The following opt-outs could not be matched to sictic-members: %s",
                ", ".join(missing_optouts),
            )
        selected = [
            person for person in selected
            if person.identifier not in excluded_identifiers
        ]

    return selected


def _markdown_table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def render_person_ranking(rows: List[dict[str, Any]]) -> str:
    lines = [
        "## Top Candidates",
        "",
        "| Rank | Full Name | Email Addresses | LinkedIn ID | Rationale |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['rank']} | "
            f"{_markdown_table_cell(row['full_name'])} | "
            f"{_markdown_table_cell(', '.join(row['email_addresses']))} | "
            f"{_markdown_table_cell(row['linkedin_id'])} | "
            f"{_markdown_table_cell(row['rationale'])} |"
        )
    return "\n".join(lines) + "\n"


async def rank_person_rows(
    source_datasets: Optional[List[str]] = None,
    skill: str = "investor_profile",
    objective: str = "",
    candidates: Optional[List[str]] = None,
    optout: Optional[List[str]] = None,
    top_k: int = 16,
    member_dataset: str = "sictic-members",
) -> List[dict[str, Any]]:
    """Rank member profiles and return structured rows."""
    if source_datasets is None:
        source_datasets = [member_dataset]
    members = persons_in_dataset(member_dataset)
    if not members:
        raise RuntimeError(f"No persons found in member dataset '{member_dataset}'.")

    selected_members = _resolve_members(members, candidates, optout)
    members_by_linkedin = {
        person.linkedin_id: person
        for person in selected_members
        if person.linkedin_id
    }
    skipped_without_linkedin = [
        person.display_name
        for person in selected_members
        if not person.linkedin_id
    ]
    if skipped_without_linkedin:
        logger.warning(
            "Skipping %d selected members without LinkedIn IDs: %s",
            len(skipped_without_linkedin),
            ", ".join(skipped_without_linkedin),
        )
    if not members_by_linkedin:
        raise RuntimeError("No selected members have LinkedIn IDs for profile ranking.")

    profiles = select_insights(source_datasets, skill)
    profile_text_by_id: dict[str, str] = {}
    profile_files_by_id: dict[str, InsightFile] = {}
    for profile in profiles:
        linkedin_id = profile.identifier
        if not linkedin_id:
            logger.warning("Skipping profile without an identifier: %s", profile.path)
            continue
        if linkedin_id not in members_by_linkedin:
            continue
        if linkedin_id in profile_files_by_id:
            raise ValueError(
                f"Multiple selected profiles found for '{linkedin_id}': "
                f"{profile_files_by_id[linkedin_id].path}, {profile.path}"
            )
        profile_files_by_id[linkedin_id] = profile

    for linkedin_id, profile in profile_files_by_id.items():
        profile_text_by_id[linkedin_id] = profile.content()

    if not profile_text_by_id:
        raise RuntimeError(
            "No profile documents remained after matching selected insights to "
            "the selected sictic-members roster."
        )

    if candidates:
        missing_profiles = [
            person.display_name
            for person in selected_members
            if person.linkedin_id not in profile_text_by_id
        ]
        if missing_profiles:
            raise ValueError(
                "The following requested candidates have no searchable profile: "
                + ", ".join(missing_profiles)
            )

    logger.info(
        "Starting ranking_top_k with %d candidates (target top_k: %d).",
        len(profile_text_by_id),
        top_k,
    )
    ranked_items, actual_top_k = await ranking_top_k(
        objective=objective,
        all_profiles=profile_text_by_id,
        top_k=top_k,
    )
    logger.info(
        "Starting ranking_rationale with top %d out of %d ranked candidates.",
        actual_top_k,
        len(ranked_items),
    )
    augmented_items = await ranking_rationale(
        ranked_items=ranked_items,
        objective=objective,
    )

    rows = []
    for item in augmented_items:
        person = members_by_linkedin[item["id"]]
        rows.append(
            {
                "rank": item.get("rank", len(rows) + 1),
                "full_name": person.display_name,
                "email_addresses": list(person.email_addresses),
                "linkedin_id": person.linkedin_id,
                "rationale": item.get("rationale", ""),
            }
        )
    return rows


async def ranking_persons(
    source_datasets: Optional[List[str]] = None,
    skill: str = "investor_profile",
    objective: str = "",
    candidates: Optional[List[str]] = None,
    optout: Optional[List[str]] = None,
    top_k: int = 16,
    member_dataset: str = "sictic-members",
) -> str:
    """Rank member profiles and return a Markdown report."""
    rows = await rank_person_rows(
        source_datasets=source_datasets,
        skill=skill,
        objective=objective,
        candidates=candidates,
        optout=optout,
        top_k=top_k,
        member_dataset=member_dataset,
    )
    result = render_person_ranking(rows)
    logger.info("[%s] ranking_persons complete.", slugify(skill))
    return result
