import re
from typing import List, Dict
from lib.storage import get_storage
from lib.adapters.linkedin import LinkedInAdapter
from lib.adapters.web_search import WebSearchAdapter
from lib.logger import get_logger
from lib.models.person import Person

logger = get_logger(__name__)

def persons_in_dataset(dataset_name: str) -> List[Person]:
    """
    Discovers all unique persons associated with a dataset; only hunts for linkedin profiles
    
    Discovery phases:
    1. Checks local LinkedIn cache for already fully-populated Person objects.
    2. Web Search (Google for dataset + site:linkedin.com/in/) to find missing profiles.
    3. Regex scan of datasets2md for explicit linkedin URLs.
    
    Returns a deduplicated list of Person objects.
    """
    discovered_persons: List[Person] = []
    dataset_lower = dataset_name.lower()
    
    def _add_person(new_p: Person):
        if not any(ex.matches(new_p) for ex in discovered_persons):
            discovered_persons.append(new_p)
    
    logger.info(f"[{dataset_name}] Starting people discovery...")
    
    # 1. Local Cache
    linkedin_adapter = LinkedInAdapter(dataset_lower)
    cached = linkedin_adapter.get_cached_persons()
    for p in cached:
        _add_person(p)
            
    # Skip web discovery for community members (too broad/already provided directly)
    if dataset_lower == "sictic_members":
        logger.info(f"[{dataset_name}] Community dataset detected. Skipping web/regex discovery.")
        return discovered_persons
        
    # 2. Web Search
    try:
        google = WebSearchAdapter()
        query = f"{dataset_name} site:linkedin.com/in/"
        logger.info(f"[{dataset_name}] Searching web for: {query}")
        results = google.search(query)
        # Import the standalone function here or at the top of the file
        from lib.adapters.linkedin import extract_linkedin_id
        for r in results:
            link = r.get("link", "")
            slug = extract_linkedin_id(link)
            if slug:
                _add_person(Person(linkedinID=slug))
    except Exception as e:
        logger.warning(f"[{dataset_name}] Web search discovery failed: {e}")
        
    # 3. Regex across datasets2md
    storage = get_storage()
    md_dir = f"datasets2md/{dataset_lower}"
    if storage.exists(md_dir):
        logger.info(f"[{dataset_name}] Scanning {md_dir} for explicit LinkedIn URLs...")
        files = storage.list(md_dir, suffix=".md")
        
        # Matches linkedin.com/in/slug (or /pub/)
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
    return discovered_persons
