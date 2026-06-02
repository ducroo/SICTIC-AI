import re
from typing import List
from lib.storage import get_storage
from lib.adapters.linkedin import LinkedInAdapter, extract_linkedin_id
from lib.adapters.web_search import WebSearchAdapter
from lib.insight_filepath import get_insight_filepath
from lib.logger import get_logger
from lib.models.person import Person
from lib.storage_domains import dataset_parsed_path
from lib.slugify import slugify

logger = get_logger(__name__)

_LINKEDIN_URL_PATTERN = re.compile(r'linkedin\.com/(?:in|pub)/([a-zA-Z0-9\-]+)', re.IGNORECASE)

def _parse_manual_persons_table(content: str) -> List[Person]:
    persons: List[Person] = []
    seen = set()
    header = None

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue

        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        normalized = [cell.strip().lower().replace("_", "") for cell in cells]
        if header is None:
            if "fullname" not in normalized or "linkedinid" not in normalized:
                continue
            header = normalized
            continue

        if all(set(cell) <= {"-", ":"} for cell in cells):
            continue

        values = dict(zip(header, cells))
        full_name = values.get("fullname", "").strip()
        linkedin_id = values.get("linkedinid", "").strip()
        if "linkedin.com/" in linkedin_id.lower():
            linkedin_id = extract_linkedin_id(linkedin_id)
        else:
            linkedin_id = slugify(linkedin_id)

        if not full_name and not linkedin_id:
            continue

        key = linkedin_id.lower() if linkedin_id else f"name:{slugify(full_name)}"
        if key in seen:
            continue
        seen.add(key)
        persons.append(Person(full_name=full_name, linkedinID=linkedin_id))

    return persons


def _render_manual_persons_table(dataset_name: str, persons: List[Person]) -> str:
    lines = [
        f"# Persons in {dataset_name}",
        "",
        "Deal leads, feel free to add or remove employees - SICTIC-AI will remember the edits; this file will never be overwritten. BTW linkedinURL = https://www.linkedin.com/in/linkedinID",
        "",
        "| full_name | linkedinID |",
        "|---|---|",
    ]
    for person in persons:
        lines.append(f"| {person.full_name} | {person.linkedinID} |")
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
    
    manual_rel = get_insight_filepath(
        dataset_name=dataset_slug,
        skill_name="persons_in_dataset",
        model="manual",
        subdir=False,
    )

    # 1. Manual Override File (Source of Truth)
    if storage.exists(manual_rel):
        logger.info(f"[{dataset_name}] Found manual persons insight: {manual_rel}")
        discovered_persons = _parse_manual_persons_table(storage.read_text(manual_rel))
        logger.info(f"[{dataset_name}] Loaded {len(discovered_persons)} persons from manual insight.")
        return discovered_persons

    # Otherwise, proceed with discovery
    discovered_persons: List[Person] = []
    
    def _add_person(new_p: Person):
        if not any(ex.matches(new_p) for ex in discovered_persons):
            discovered_persons.append(new_p)
    
    logger.info(f"[{dataset_name}] Starting people discovery...")
    
    # 2. Local Cache
    linkedin_adapter = LinkedInAdapter(dataset_slug)
    cached = linkedin_adapter.get_cached_persons()
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
                    _add_person(Person(linkedinID=slug))
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
                            _add_person(Person(linkedinID=match.lower()))
                except Exception as e:
                    logger.warning(f"Failed to read {f} for regex scanning: {e}")
                    
    logger.info(f"[{dataset_name}] Discovery complete. Found {len(discovered_persons)} unique persons.")
    
    # Write the results to the manual insight so deal leads can edit it later.
    storage.write_text(manual_rel, _render_manual_persons_table(dataset_name, discovered_persons))
    logger.info(f"[{dataset_name}] Wrote discovered persons list to {manual_rel}")
    
    return discovered_persons
