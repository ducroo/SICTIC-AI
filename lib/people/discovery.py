"""Read and render the authoritative editable person roster. No discovery."""

from typing import List
from lib.storage import get_storage
from lib.people.linkedin import extract_linkedin_id
from lib.insights import InsightFile
from lib.infrastructure.logging import get_logger
from lib.people.model import Person, normalize_email_addresses
from lib.slugify import slugify

logger = get_logger(__name__)



def _manual_header_key(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    if normalized in {"fullname", "full-name"}:
        return "full-name"
    if normalized in {"linkedinid", "linkedin-id"}:
        return "linkedin-id"
    if normalized in {"emailaddresses", "email-addresses"}:
        return "email-addresses"
    return normalized

def _markdown_cell_text(cell: str) -> str:
    return cell.strip().replace("\\_", "_").replace("\\-", "-").replace("\\=", "=")


def _markdown_table_cell(value: str) -> str:
    return value.replace("|", "\\|").strip()


def _parse_manual_persons_table(content: str) -> List[Person] | None:
    persons: List[Person] = []
    seen = set()
    header = None

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.lower().startswith(("http://", "https://")) and "linkedin.com/" in stripped.lower():
            linkedin_slug = extract_linkedin_id(stripped)
            key = linkedin_slug.lower()
            if key not in seen:
                seen.add(key)
                persons.append(
                    Person(
                        linkedin_id=linkedin_slug,
                    )
                )
            continue

        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue

        cells = [_markdown_cell_text(cell) for cell in stripped.strip("|").split("|")]
        normalized = [_manual_header_key(cell) for cell in cells]
        if header is None:
            if "full-name" not in normalized or "linkedin-id" not in normalized:
                continue
            header = normalized
            continue

        if all(set(cell) <= {"-", ":"} for cell in cells):
            continue

        values = dict(zip(header, cells))
        full_name = values.get("full-name", "").strip()
        linkedin_id = values.get("linkedin-id", "").strip()
        email_addresses = normalize_email_addresses(values.get("email-addresses", ""))
        if "linkedin.com/" in linkedin_id.lower():
            linkedin_id = extract_linkedin_id(linkedin_id)
        else:
            linkedin_id = slugify(linkedin_id)

        if not full_name and not linkedin_id and not email_addresses:
            continue

        key = linkedin_id.lower() if linkedin_id else ",".join(email_addresses) or f"name:{slugify(full_name)}"
        if key in seen:
            continue
        seen.add(key)
        persons.append(
            Person(
                full_name=full_name,
                linkedin_id=linkedin_id,
                email_addresses=email_addresses,
            )
        )

    return persons if header is not None or persons else None


def _render_manual_persons_table(dataset_name: str, persons: List[Person]) -> str:
    lines = [
        f"# Persons in {dataset_name}",
        "",
        "Deal leads, feel free to add or remove employees - SICTIC-AI will remember the edits; this file will never be overwritten.",
        "",
        "| full-name | linkedin-id | email-addresses |",
        "|---|---|---|",
    ]
    for person in persons:
        lines.append(
            f"| {_markdown_table_cell(person.full_name)} | "
            f"{_markdown_table_cell(person.linkedin_id)} | "
            f"{_markdown_table_cell(', '.join(person.email_addresses))} |"
        )
    return "\n".join(lines) + "\n"


def manual_persons_in_dataset(dataset_name: str) -> List[Person] | None:
    """Read the authoritative editable roster without discovery or enrichment."""
    insight = InsightFile(
        dataset=slugify(dataset_name), skill="persons_in_dataset", model="manual"
    )
    storage = get_storage()
    if not storage.exists(insight.path):
        return None
    persons = _parse_manual_persons_table(storage.read_text(insight.path))
    if persons is None:
        raise ValueError(f"Unsupported manual persons roster: {insight.path}")
    logger.info("[%s] Loaded %d persons from manual roster %s", dataset_name, len(persons), insight.path)
    return persons


def persons_in_dataset(dataset_name: str) -> List[Person]:
    """Read the roster for synchronous consumers; discovery belongs to the skill."""
    persons = manual_persons_in_dataset(dataset_name)
    if persons is None:
        raise FileNotFoundError(
            f"No persons roster for {dataset_name}; run the persons_in_dataset skill first."
        )
    return persons
