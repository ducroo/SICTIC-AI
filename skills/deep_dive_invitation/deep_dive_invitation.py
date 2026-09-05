"""Prepare a review-only deep-dive invitation as a managed Markdown insight."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePosixPath
import re

from lib.infrastructure.configuration import config_cache_key, load_repository_config
from lib.infrastructure.logging import get_logger
from lib.insights import InsightFile, InsightResult
from lib.model_config import llm_model
from lib.people import Person, markdown_table_to_person_objects
from lib.slugify import slugify
from lib.storage import get_storage
from skills.dealum_import.dealum_import import dealum_import
from skills.expert_search.expert_search import expert_search
from skills.member_preferences.member_preferences import (
    member_preferences,
    preferences_for,
)
from skills.startup_profile.startup_profile import startup_profile

logger = get_logger(__name__)

_CONTACT_RE = re.compile(r"^\s*(.*?)\s*<\s*([^<>]+)\s*>\s*$")
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_MARKDOWN_HARD_BREAK = "  "


@dataclass
class RecipientResolution:
    role: str
    person: Person
    source: str
    reference_email: str
    selected_email: str
    status: str


def parse_people_csv(value: str | None) -> list[Person]:
    """Parse comma-separated ``Name <email>``, email-only, or name-only entries."""
    if not value:
        return []
    people: list[Person] = []
    for entry in (part.strip() for part in value.split(",")):
        if not entry:
            continue
        match = _CONTACT_RE.match(entry)
        if match:
            name, email = match.groups()
            if not _EMAIL_RE.match(email.strip()):
                raise ValueError(f"Invalid email address in recipient entry: {entry!r}")
            people.append(Person(full_name=name.strip(), email_addresses=[email]))
        elif _EMAIL_RE.match(entry):
            people.append(Person(email_addresses=[entry]))
        else:
            people.append(Person(full_name=entry))
    return people


def _person_snapshot(person: Person) -> dict[str, object]:
    return {
        "full_name": person.full_name,
        "linkedin_id": person.linkedin_id,
        "email_addresses": person.email_addresses,
        "member_preferences": preferences_for(person),
    }


def _preferred_member_email(person: Person) -> str:
    for domain in ("investor.sictic.ch", "sictic.ch"):
        found = next(
            (
                email
                for email in person.email_addresses
                if email.rsplit("@", 1)[-1].lower() == domain
            ),
            "",
        )
        if found:
            return found
    return person.email_addresses[0] if person.email_addresses else ""


def _exact_member_matches(reference: Person, members: list[Person]) -> list[Person]:
    if reference.email_addresses:
        emails = set(reference.email_addresses)
        matches = [person for person in members if emails & set(person.email_addresses)]
        if matches:
            return matches
    if reference.linkedin_id:
        matches = [
            person for person in members if person.linkedin_id == reference.linkedin_id
        ]
        if matches:
            return matches
    normalized_name = " ".join(reference.full_name.casefold().split())
    if normalized_name:
        return [
            person
            for person in members
            if " ".join(person.full_name.casefold().split()) == normalized_name
        ]
    return []


def _reconcile_investors(
    supplied: list[Person],
    members: list[Person],
) -> tuple[list[RecipientResolution], list[str], list[str]]:
    resolutions: list[RecipientResolution] = []
    action_notices: list[str] = []
    informational_notices: list[str] = []
    for supplied_person in _merge_people([], supplied):
        reference_email = (
            supplied_person.email_addresses[0] if supplied_person.email_addresses else ""
        )
        matches = _exact_member_matches(supplied_person, members)
        person = Person(
            full_name=supplied_person.full_name,
            linkedin_id=supplied_person.linkedin_id,
            email_addresses=list(supplied_person.email_addresses),
            adhoc_data=dict(supplied_person.adhoc_data),
        )
        if len(matches) == 1:
            member = matches[0]
            person.merge(member)
            selected_email = reference_email or _preferred_member_email(member)
            source = "Joëlle + sictic-members"
            status = "matched"
        elif len(matches) > 1:
            selected_email = reference_email
            source = "Joëlle"
            status = "ambiguous member match"
            action_notices.append(
                f"Ambiguous member match for {person.display_name}; the supplied "
                "address remains in Cc. Verify the recipient."
            )
        else:
            selected_email = reference_email
            source = "Joëlle"
            status = "unmatched"
            informational_notices.append(
                f"Interested investor {person.display_name} was not matched in "
                "sictic-members. Verify the recipient."
            )

        if not selected_email:
            action_notices.append(
                f"Interested investor {person.display_name} has no email address; "
                "they are omitted from Cc until one is inserted."
            )
            status = f"{status}; missing email"
        resolutions.append(
            RecipientResolution(
                role="Interested investor",
                person=person,
                source=source,
                reference_email=reference_email,
                selected_email=selected_email,
                status=status,
            )
        )
    return resolutions, action_notices, informational_notices


def _merge_people(primary: list[Person], additions: list[Person]) -> list[Person]:
    merged = list(primary)
    for addition in additions:
        exact_matches = _exact_member_matches(addition, merged)
        match = exact_matches[0] if len(exact_matches) == 1 else None
        if match:
            match.merge(addition)
        else:
            merged.append(addition)
    return merged


def _dealum_contact(application_path: str | None) -> Person | None:
    if not application_path:
        return None
    raw_path = str(PurePosixPath(application_path).with_name("application.raw.json"))
    storage = get_storage()
    if not storage.exists(raw_path):
        return None
    application = json.loads(storage.read_text(raw_path))
    contact = application.get("contact") or {}
    name = " ".join(
        part.strip()
        for part in (contact.get("firstName") or "", contact.get("lastName") or "")
        if part.strip()
    )
    email = contact.get("email") or ""
    return Person(full_name=name, email_addresses=[email] if email else [])


def _founder_resolutions(
    supplied: list[Person],
    dealum_contact: Person | None,
) -> tuple[list[RecipientResolution], list[str]]:
    founders = _merge_people(supplied, [dealum_contact] if dealum_contact else [])
    resolutions: list[RecipientResolution] = []
    notices: list[str] = []
    if not founders:
        founders = [Person()]
    for founder in founders:
        email = founder.email_addresses[0] if founder.email_addresses else ""
        if not email:
            notices.append(
                f"Founder {founder.display_name or '(name unavailable)'} has no email; "
                "insert it before sending."
            )
        source = "Joëlle"
        if dealum_contact and _exact_member_matches(dealum_contact, [founder]):
            source = "Joëlle + Dealum" if supplied else "Dealum"
        resolutions.append(
            RecipientResolution(
                role="Founder",
                person=founder,
                source=source,
                reference_email=email,
                selected_email=email or "<insert founder email here>",
                status="ready" if email else "missing email",
            )
        )
    return resolutions, notices


def _expert_exclusions(
    investor_resolutions: list[RecipientResolution],
    members: list[Person],
    preference_key: str,
) -> tuple[list[str], list[str], list[str]]:
    preference_exclusions: list[str] = []
    for member in members:
        if preferences_for(member).get(preference_key, "standard") == "none":
            preference_exclusions.append(member.identifier)
    investor_exclusions: list[str] = []
    for resolution in investor_resolutions:
        matches = _exact_member_matches(resolution.person, members)
        investor_exclusions.extend(match.identifier for match in matches)
    preference_exclusions = list(dict.fromkeys(preference_exclusions))
    investor_exclusions = list(dict.fromkeys(investor_exclusions))
    combined = list(dict.fromkeys(preference_exclusions + investor_exclusions))
    return combined, preference_exclusions, investor_exclusions


def _select_experts(
    markdown: str,
    *,
    startup_slug: str,
    members: list[Person],
    investor_resolutions: list[RecipientResolution],
    preference_key: str,
    limit: int,
) -> list[Person]:
    ranked = markdown_table_to_person_objects(
        markdown,
        tag=f"expert_search:{startup_slug}",
    )
    occupied = {
        resolution.selected_email.lower()
        for resolution in investor_resolutions
        if resolution.selected_email
    }
    selected: list[Person] = []
    for candidate in ranked:
        matches = _exact_member_matches(candidate, members)
        if len(matches) != 1:
            continue
        member = matches[0]
        candidate.merge(member)
        if preferences_for(member).get(preference_key, "standard") == "none":
            continue
        email = _preferred_member_email(candidate)
        if not email or email.lower() in occupied:
            continue
        candidate.email_addresses = [email] + [
            value for value in candidate.email_addresses if value != email
        ]
        selected.append(candidate)
        occupied.add(email.lower())
        if len(selected) >= limit:
            break
    return selected


def _escape_cell(value: str) -> str:
    return value.replace("|", r"\|").replace("\n", " ").strip()


def _linkedin_url(person: Person) -> str:
    return f"https://www.linkedin.com/in/{person.linkedin_id}" if person.linkedin_id else ""


def _investor_table(resolutions: list[RecipientResolution]) -> str:
    lines = [
        "| Full Name | Email Address | LinkedIn Profile |",
        "|---|---|---|",
    ]
    if not resolutions:
        lines.append("| — | — | — |")
    for resolution in resolutions:
        email = resolution.selected_email or "<insert email here>"
        linkedin_url = _linkedin_url(resolution.person)
        linkedin = f"[LinkedIn]({linkedin_url})" if linkedin_url else "—"
        lines.append(
            f"| {_escape_cell(resolution.person.display_name)} | "
            f"{_escape_cell(email)} | {linkedin} |"
        )
    return "\n".join(lines)


def _reconciliation_table(
    founders: list[RecipientResolution],
    investors: list[RecipientResolution],
) -> str:
    lines = [
        "| Role | Name | Source | Reference email | Selected email | LinkedIn ID | Status |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in founders + investors:
        lines.append(
            "| " + " | ".join(
                _escape_cell(value)
                for value in (
                    item.role,
                    item.person.display_name,
                    item.source,
                    item.reference_email,
                    item.selected_email,
                    item.person.linkedin_id,
                    item.status,
                )
            ) + " |"
        )
    return "\n".join(lines)


def _address_label(person: Person, email: str) -> str:
    name = person.full_name.strip()
    if name and email.startswith("<insert "):
        return f"{name} {email}"
    if name and name.casefold() != email.casefold():
        return f"{name} <{email}>"
    return email


def _recipient_header(
    label: str,
    recipients: list[tuple[Person, str]],
) -> list[str]:
    """Render address lines that survive native Google Docs round-tripping."""
    values = [_address_label(person, email) for person, email in recipients]
    lines = [f"{label}:{_MARKDOWN_HARD_BREAK}"]
    lines.extend(
        f"{value}{',' if index < len(values) - 1 else ''}{_MARKDOWN_HARD_BREAK}"
        for index, value in enumerate(values)
    )
    return lines


async def deep_dive_invitation(
    startup: str,
    founders: list[Person] | None = None,
    investors: list[Person] | None = None,
) -> InsightResult:
    """Create and save a review-only deep-dive invitation Markdown draft."""
    supplied_founders = founders or []
    supplied_investors = investors or []
    config = load_repository_config("deep_dive_invitation")
    template = config["email_template"]
    settings = config["settings"]

    dealum = await dealum_import(startup)
    startup_slug = dealum.dataset_slug
    await startup_profile(startup_slug)

    members = member_preferences("sictic-members")
    founder_resolutions, founder_notices = _founder_resolutions(
        supplied_founders,
        _dealum_contact(dealum.application_path),
    )
    (
        investor_resolutions,
        investor_action_notices,
        investor_informational_notices,
    ) = _reconcile_investors(
        supplied_investors,
        members,
    )

    preference_key = settings["preference_key"]
    exclusions, preference_exclusions, investor_exclusions = _expert_exclusions(
        investor_resolutions,
        members,
        preference_key,
    )
    [expert_insight] = await expert_search(
        startup_slug,
        exclude_experts=exclusions,
        top_k=settings["expert_search_candidates"],
    )
    experts = _select_experts(
        expert_insight.content(),
        startup_slug=startup_slug,
        members=members,
        investor_resolutions=investor_resolutions,
        preference_key=preference_key,
        limit=settings["max_experts"],
    )

    action_notices = [*founder_notices, *investor_action_notices]
    informational_notices = list(investor_informational_notices)
    if supplied_investors:
        informational_notices.insert(
            0,
            "Automatic extraction of interested investors from Dealum is not "
            "configured. This draft uses manually supplied Funding-tab information. "
            "Verify the Cc recipients against Dealum before sending.",
        )
    else:
        action_notices.insert(
            0,
            "Automatic extraction of interested investors from Dealum is not "
            "configured, and no interested investors were supplied. Check the "
            "Funding tab and complete the Cc recipients before sending.",
        )

    to_addresses = list(dict.fromkeys(
        item.selected_email for item in founder_resolutions
    ))
    cc_addresses = list(dict.fromkeys(
        item.selected_email for item in investor_resolutions if item.selected_email
    ))
    occupied = {
        address.lower()
        for address in to_addresses + cc_addresses
        if "@" in address
    }
    bcc_people = [
        expert
        for expert in experts
        if expert.email_addresses and expert.email_addresses[0].lower() not in occupied
    ]
    bcc_addresses = [expert.email_addresses[0] for expert in bcc_people]

    body = template
    body = body.replace("{{investor_table}}", _investor_table(investor_resolutions))
    body = body.replace("{{dealum_url}}", dealum.dealum_url or "<insert Dealum link here>")

    expert_digest = hashlib.sha256(expert_insight.content().encode()).hexdigest()
    cache_key = config_cache_key(
        config,
        [_person_snapshot(person) for person in supplied_founders],
        [_person_snapshot(person) for person in supplied_investors],
        [
            {
                "identifier": member.identifier,
                "preferences": preferences_for(member),
            }
            for member in members
        ],
        {"expert_insight": expert_insight.path, "content_sha256": expert_digest},
    )
    insight = InsightFile(
        dataset=startup_slug,
        skill="deep_dive_invitation",
        model=llm_model(),
        source_datasets=[startup_slug, "sictic-members"],
        config_key=cache_key,
    )
    if reusable := insight.find(selection="reusable"):
        return [reusable]

    content = "\n".join(
        [
            "# Review notices",
            "",
            "## Action required before sending",
            "",
            *(f"- {notice}" for notice in action_notices),
            *([] if action_notices else ["- None."]),
            "",
            "## Informational",
            "",
            *(f"- {notice}" for notice in informational_notices),
            *([] if informational_notices else ["- None."]),
            "",
            "## Recipient reconciliation",
            "",
            _reconciliation_table(founder_resolutions, investor_resolutions),
            "",
            "- Member preference opt-outs excluded from expert search: "
            f"{len(preference_exclusions)}",
            "- Interested members excluded from expert search: "
            f"{len(investor_exclusions)}",
            f"- Usable experts selected for Bcc: {len(bcc_addresses)}",
            "",
            "# Email draft",
            "",
            f"From:{_MARKDOWN_HARD_BREAK}",
            settings["from_address"],
            "",
            *_recipient_header(
                "To",
                [
                    (item.person, item.selected_email)
                    for item in founder_resolutions
                ],
            ),
            "",
            *_recipient_header(
                "Cc",
                [
                    (item.person, item.selected_email)
                    for item in investor_resolutions
                    if item.selected_email
                ],
            ),
            "",
            *_recipient_header(
                "Bcc",
                [(expert, expert.email_addresses[0]) for expert in bcc_people],
            ),
            "",
            f"Subject:{_MARKDOWN_HARD_BREAK}",
            f"{dealum.dealum_name or startup}: Deep Dive Setup",
            "",
            body.strip(),
            "",
        ]
    )
    insight.save(content)
    logger.info("[%s] Saved deep-dive invitation draft to %s", startup_slug, insight.path)
    return [insight]
