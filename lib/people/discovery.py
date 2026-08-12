"""Discover and maintain the editable person list for a dataset."""

import re
from typing import List
from lib.storage import get_storage
from lib.linkedin import LinkedInResolver, extract_linkedin_id
from lib.adapters.web_search import WebSearchAdapter
from lib.insights import InsightFile
from lib.logger import get_logger
from lib.people.model import Person, normalize_email_addresses
from lib.datasets.paths import dataset_parsed_path
from lib.slugify import slugify

logger = get_logger(__name__)

_LINKEDIN_URL_PATTERN = re.compile(r'linkedin\.com/(?:in|pub)/([a-zA-Z0-9\-]+)', re.IGNORECASE)


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


def persons_in_dataset(dataset_name: str) -> List[Person]:
    """
    Discovers all unique persons associated with a dataset; only hunts for linkedin profiles
    
    Discovery phases:
    1. Checks if a manual override file exists (Source of Truth).
    2. Checks local LinkedIn cache for already fully-populated Person objects.
    3. Web Search (Google for dataset + site:linkedin.com/in/) to find missing profiles.
    4. Regex scan of datasets2md for explicit linkedin URLs.
    
    Returns a deduplicated list of Person objects.
    """
    storage = get_storage()
    dataset_slug = slugify(dataset_name)

    manual_insight = InsightFile(
        dataset=dataset_slug,
        skill="persons_in_dataset",
        model="manual",
    )
    manual_rel = manual_insight.path

    # 1. Manual Override File (Source of Truth)
    if storage.exists(manual_rel):
        logger.info(f"[{dataset_name}] Found manual persons insight: {manual_rel}")
        discovered_persons = _parse_manual_persons_table(storage.read_text(manual_rel))
        if discovered_persons is not None:
            logger.info(f"[{dataset_name}] Loaded {len(discovered_persons)} persons from manual insight.")
            return discovered_persons
        logger.info(f"[{dataset_name}] Ignoring unsupported manual persons insight: {manual_rel}")

    # Otherwise, proceed with discovery
    discovered_persons: List[Person] = []
    
    def _add_person(new_p: Person):
        if not any(ex.matches(new_p) for ex in discovered_persons):
            discovered_persons.append(new_p)
    
    logger.info(f"[{dataset_name}] Starting people discovery...")
    
    # 2. Local Cache
    linkedin_resolver = LinkedInResolver(dataset_slug)
    cached = linkedin_resolver.get_cached_persons()
    for p in cached:
        _add_person(p)
            
    # Skip web discovery for community members (too broad/already provided directly)
    if dataset_slug != "sictic-members":
        # 3. Web Search
        try:
            google = WebSearchAdapter()
            query = f"{dataset_name} site:linkedin.com/in/"
            logger.info(f"[{dataset_name}] Searching web for: {query}")
            results = google.search(query)
            for r in results:
                link = r.get("link", "")
                slug = extract_linkedin_id(link)
                if slug:
                    _add_person(Person(linkedin_id=slug))
        except Exception as e:
            logger.warning(f"[{dataset_name}] Web search discovery failed: {e}")
            
        # 4. Regex across datasets2md
        md_dir = dataset_parsed_path(dataset_slug)
        if storage.exists(md_dir):
            logger.info(f"[{dataset_name}] Scanning {md_dir} for explicit LinkedIn URLs...")
            files = storage.list(md_dir, suffix=".md")
            
            for f in files:
                try:
                    content = storage.read_text(f"{md_dir}/{f}")
                    matches = _LINKEDIN_URL_PATTERN.findall(content)
                    for match in matches:
                        if match:
                            _add_person(Person(linkedin_id=match.lower()))
                except Exception as e:
                    logger.warning(f"Failed to read {f} for regex scanning: {e}")
                    
    logger.info(f"[{dataset_name}] Discovery complete. Found {len(discovered_persons)} unique persons.")
    
    # Write the results to the manual insight so deal leads can edit it later.
    manual_insight.save(
        _render_manual_persons_table(dataset_name, discovered_persons)
    )
    logger.info(f"[{dataset_name}] Wrote discovered persons list to {manual_rel}")
    
    return discovered_persons
