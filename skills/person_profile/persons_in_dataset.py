import re
from typing import List, Dict
from lib.storage import get_storage
from lib.adapters.linkedin import LinkedInAdapter, extract_linkedin_id
from lib.adapters.web_search import WebSearchAdapter
from lib.logger import get_logger
from lib.models.person import Person
from lib.insight_filepath import get_insight_filepath

logger = get_logger(__name__)

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
    dataset_lower = dataset_name.lower()
    
    insight_path = get_insight_filepath(
        dataset_name=dataset_lower,
        skill_name="persons_in_dataset",
        model="manual",
        subdir=False
    )
    
    # 1. Manual Override File (Source of Truth)
    if storage.exists(insight_path):
        logger.info(f"[{dataset_name}] Found manual override file: {insight_path}")
        content = storage.read_text(insight_path)
        
        discovered_persons = []
        seen = set()
        
        # Extract all linkedin IDs using regex
        pattern = re.compile(r'linkedin\.com/(?:in|pub)/([a-zA-Z0-9\-]+)', re.IGNORECASE)
        for match in pattern.finditer(content):
            slug = match.group(1).lower()
            if slug not in seen:
                seen.add(slug)
                discovered_persons.append(Person(linkedinID=slug))
                
        logger.info(f"[{dataset_name}] Loaded {len(discovered_persons)} persons from manual file.")
        return discovered_persons

    # Otherwise, proceed with discovery
    discovered_persons: List[Person] = []
    
    def _add_person(new_p: Person):
        if not any(ex.matches(new_p) for ex in discovered_persons):
            discovered_persons.append(new_p)
    
    logger.info(f"[{dataset_name}] Starting people discovery...")
    
    # 2. Local Cache
    linkedin_adapter = LinkedInAdapter(dataset_lower)
    cached = linkedin_adapter.get_cached_persons()
    for p in cached:
        _add_person(p)
            
    # Skip web discovery for community members (too broad/already provided directly)
    if dataset_lower != "sictic_members":
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
        md_dir = f"datasets2md/{dataset_lower}"
        if storage.exists(md_dir):
            logger.info(f"[{dataset_name}] Scanning {md_dir} for explicit LinkedIn URLs...")
            files = storage.list(md_dir, suffix=".md")
            
            pattern = re.compile(r'linkedin\.com/(?:in|pub)/([a-zA-Z0-9\-]+)', re.IGNORECASE)
            
            for f in files:
                try:
                    content = storage.read_text(f"{md_dir}/{f}")
                    matches = pattern.findall(content)
                    for match in matches:
                        if match:
                            _add_person(Person(linkedinID=match.lower()))
                except Exception as e:
                    logger.warning(f"Failed to read {f} for regex scanning: {e}")
                    
    logger.info(f"[{dataset_name}] Discovery complete. Found {len(discovered_persons)} unique persons.")
    
    # Write the results to the manual file so deal leads can edit it later
    lines = [
        f"# Persons in {dataset_name}",
        "",
        "Deal leads, feel free to add or remove employees - SICTIC-AI will remember the edits; this file will never be overwritten.",
        ""
    ]
    for p in discovered_persons:
        if p.linkedinID:
            lines.append(f"https://www.linkedin.com/in/{p.linkedinID}/")
            
    storage.write_text(insight_path, "\n".join(lines) + "\n")
    logger.info(f"[{dataset_name}] Wrote discovered persons list to {insight_path}")
    
    return discovered_persons
