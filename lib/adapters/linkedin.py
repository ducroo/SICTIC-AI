import json
import re
import unicodedata
from typing import List, Dict, Any
from rapidfuzz import process, fuzz

from lib.logger import get_logger
from lib.storage import get_storage
from lib.env import get_env_var
from lib.adapters.apify import ApifyAdapter
from lib.adapters.web_search import WebSearchAdapter
from lib.models.person import Person
from lib.storage_domains import dataset_raw_path, list_dataset_names

logger = get_logger(__name__)

def extract_linkedin_id(url: str) -> str:
    """Extracts the username slug from a LinkedIn URL. This slug is the absolute source of truth for IDs."""
    if not url:
        return ""
    url = url.split('?')[0].strip('/')
    match = re.search(r'linkedin\.com/(?:in|pub)/([^/]+)', url, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    return slugify(url)

class LinkedInAdapter:
    def __init__(self, dataset_name: str):
        """
        Initializes the LinkedIn adapter for a specific dataset.
        Instantly loads the cache, sanitizes names, builds an in-memory RapidFuzz index,
        and loads the missing_profiles state registry.
        """
        self.dataset_name = dataset_name
        self.cache_rel = f"{dataset_raw_path(dataset_name)}/linkedin"
        
        # Load registry path
        self.registry_filepath = _get_global_registry_path()
            
        self.storage = get_storage()
        self.apify = ApifyAdapter()
        self.google = WebSearchAdapter()
        
        # In-memory State
        self.cache: Dict[str, Person] = {}  # linkedinID -> Person
        self.fuzz_index: List[Dict[str, str]] = []  # [{"full_name": ..., "linkedinID": ...}]
        self.registry: Dict[str, Dict[str, Any]] = {} # id/name -> registry status
        
        self._initialize_state()

    def _sanitize_name(self, name: str) -> str:
        """Preserves Latin characters (including accents), strips emojis and weird symbols."""
        if not name:
            return ""
        # Remove symbols/emojis (Category 'So' = Symbol, Other; 'C' = Control)
        clean = ''.join(c for c in name if not unicodedata.category(c).startswith(('So', 'C'))).strip()
        # Collapse multiple spaces
        return re.sub(r'\s+', ' ', clean)

    def _read_cached_json(self, filename: str) -> dict | None:
        try:
            return json.loads(self.storage.read_text(f"{self.cache_rel}/{filename}"))
        except Exception:
            return None

    def _write_cached_json(self, filename: str, data: dict) -> None:
        self.storage.write_text(f"{self.cache_rel}/{filename}", json.dumps(data, indent=2))

    def _initialize_state(self):
        """Loads all cache files into memory and builds the fuzzy match index & registry state."""
        import os
        
        # Load global registry state
        if os.path.exists(self.registry_filepath):
            try:
                with open(self.registry_filepath, 'r', encoding='utf-8') as f:
                    full_registry = json.load(f)
                    # Filter registry memory to just this dataset
                    self.registry = {k: v for k, v in full_registry.items() if v.get("dataset") == self.dataset_name}
            except Exception as e:
                logger.error(f"Failed to load global missing registry: {e}")

        if not self.storage.exists(self.cache_rel):
            return

        files = [f for f in self.storage.list(self.cache_rel, suffix=".json")]
        
        for filename in files:
            # Load standard profile cache
            data = self._read_cached_json(filename)
            if not data:
                continue
                
            linkedinID = filename.replace(".json", "")
            
            # Reconstruct name
            raw_name = data.get("fullName", "")
            if not raw_name:
                first = data.get("firstName", "")
                last = data.get("lastName", "")
                raw_name = f"{first} {last}".strip()
                
            sanitized_name = self._sanitize_name(raw_name)
            
            # Build Standard Person Object
            person_wrapper = Person(
                full_name=sanitized_name or raw_name,
                linkedinID=linkedinID,
                linkedin_profile=data
            )
            
            self.cache[linkedinID] = person_wrapper
            if sanitized_name:
                self.fuzz_index.append({
                    "full_name": sanitized_name,
                    "linkedinID": linkedinID
                })

    def _save_registry(self):
        """Persists the missing_profiles state machine to disk globally."""
        import os
        full_registry = {}
        if os.path.exists(self.registry_filepath):
            try:
                with open(self.registry_filepath, 'r', encoding='utf-8') as f:
                    full_registry = json.load(f)
            except Exception:
                pass
                
        # Merge this dataset's registry changes into the global object
        full_registry.update(self.registry)
        
        try:
            with open(self.registry_filepath, 'w', encoding='utf-8') as f:
                json.dump(full_registry, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to write global missing registry: {e}")

    def _clean_linkedin_data(self, data: dict) -> dict:
        """Aggressively strips unnecessary objects, IDs, URLs, and empty fields."""
        # We preserve high-signal fields like skills, projects, languages, publications, etc.
        # We only drop pure network-graph data and extremely fluffy/long text (recommendations).
        keys_to_remove = [
            "peopleAlsoViewed", "similarProfiles", "recommendations"
        ]
        
        def _clean_node(node):
            if isinstance(node, dict):
                cleaned = {}
                for k, v in node.items():
                    if k in keys_to_remove:
                        continue
                    if "url" in k.lower() or "image" in k.lower() or "urn" in k.lower() or k.startswith("multiLocale"):
                        continue
                    cleaned_val = _clean_node(v)
                    if cleaned_val not in (None, "", [], {}):
                        cleaned[k] = cleaned_val
                return cleaned
            elif isinstance(node, list):
                cleaned_list = [_clean_node(item) for item in node]
                return [item for item in cleaned_list if item not in (None, "", [], {})]
            else:
                if isinstance(node, str) and node.startswith("http"):
                    return None
                return node

        return _clean_node(data)

    def _extract_linkedin_url(self, query: str) -> str | None:
        try:
            results = self.google.search(f"{query} site:linkedin.com/in/")
            for r in results:
                if 'linkedin.com/in/' in r.get('link', ''):
                    return r['link']
        except Exception as e:
            logger.warning(f"Google search failed for {query}: {e}")
        return None

    def get_cached_persons(self) -> List[Person]:
        """Returns the fully populated, in-memory list of person objects."""
        return list(self.cache.values())

    def get_all_persons(self) -> List[str]:
        """Returns all human-readable names known from the local LinkedIn cache."""
        names = []
        for person in self.get_cached_persons():
            name = person.display_name
            if name:
                names.append(name)
        return sorted(set(names))

    def get_profiles(self, person_list: List[Person], allow_scrape: bool = True) -> List[Person]:
        """
        Takes a list of sparse Person objects (full_name and/or linkedinID) and fills in the gaps.
        Executes caching, fuzzy matching, deduplicated web searching, and optional blocking Apify batch scrapes.
        Returns a list of cleanly hydrated Person objects.
        """
        result: List[Person] = []
        to_scrape_urls = []
        to_scrape_ids = []

        for p in person_list:
            raw_name = p.full_name
            linkedinID = p.linkedinID
                    
            sanitized_name = self._sanitize_name(raw_name)
                
            # Define placeholder Person
            placeholder = Person(
                full_name=sanitized_name or raw_name,
                linkedinID=linkedinID
            )
                
            # --- STEP A: Cache Lookup ---
            
            # 1. Exact ID Match
            if linkedinID and linkedinID in self.cache:
                result.append(self.cache[linkedinID])
                continue
                
            # 2. Fuzzy Name Match
            matched_id = None
            if sanitized_name and self.fuzz_index:
                names = [entry["full_name"] for entry in self.fuzz_index]
                matches = process.extract(sanitized_name, names, scorer=fuzz.token_sort_ratio, limit=1)
                if matches:
                    best_match, score, index = matches[0]
                    if score >= 90:  # Strict threshold to prevent false positives
                        matched_id = self.fuzz_index[index]["linkedinID"]
                        
            if matched_id and matched_id in self.cache:
                logger.info(f"Fuzzy matched '{sanitized_name}' to cache '{matched_id}' (score: {score})")
                result.append(self.cache[matched_id])
                continue
                
            # --- STEP B: Handle Misses (Registry & Web Search) ---
            
            registry_key = linkedinID if linkedinID else sanitized_name
            if not registry_key:
                logger.warning("Person provided with no name and no ID/URL. Skipping entirely.")
                continue
                
            registry_entry = self.registry.get(registry_key)
            
            # Consolidated Registry Checks
            if registry_entry:
                status = registry_entry.get("status")
                if status == "DO_NOT_SCRAPE":
                    logger.info(f"Skipping {registry_key}: Permanently marked DO_NOT_SCRAPE.")
                else:
                    logger.info(f"Skipping automated scrape for {registry_key}: Already in registry ({status}). Must be scraped manually.")
                result.append(placeholder)
                continue
                
            # If no ID exists, attempt Web Search to find it
            if not linkedinID:
                logger.info(f"No LinkedIn URL for '{sanitized_name}'. Searching web...")
                url = self._extract_linkedin_url(f"{sanitized_name} {self.dataset_name}")
                if url:
                    linkedinID = extract_linkedin_id(url)
                    registry_key = linkedinID  # Upgrade registry key to the actual ID
                    placeholder.linkedinID = linkedinID  # Update placeholder with new ID
                else:
                    logger.warning(f"URL not found via Web Search for '{sanitized_name}'.")
                    self.registry[registry_key] = {
                        "dataset": self.dataset_name,
                        "full_name": sanitized_name or raw_name,
                        "linkedinID": "",
                        "status": "URL_NOT_FOUND"
                    }
                    self._save_registry()
                    result.append(placeholder)
                    continue
                    
            # Stage for Apify Scrape
            self.registry[registry_key] = {
                "dataset": self.dataset_name,
                "full_name": sanitized_name or raw_name,
                "linkedinID": linkedinID,
                "status": "PENDING"
            }
            
            target_url = f"https://www.linkedin.com/in/{linkedinID}/"
            to_scrape_urls.append(target_url)
            to_scrape_ids.append(linkedinID)
            
            # Add the wrapper to the result set (will be updated if scrape succeeds)
            result.append(placeholder)
            
        self._save_registry()
        
        # --- STEP C: Synchronous Scraping ---
        if to_scrape_urls and allow_scrape:
            unique_urls = list(set(to_scrape_urls))
            logger.info(f"Initiating blocking batch scrape for {len(unique_urls)} profiles...")
            try:
                # Blocks/waits for up to ~10 mins depending on Apify adapter settings
                scrape_results = self.apify.run_actor(
                    actor_id="dev_fusion/Linkedin-Profile-Scraper", 
                    run_input={"urls": unique_urls}
                )
                
                # --- STEP D: Reconciliation ---
                scraped_ids = set()
                for res in scrape_results:
                    cleaned = self._clean_linkedin_data(res)
                    url = res.get("publicIdentifier", "") or res.get("url", "")
                    scraped_id = extract_linkedin_id(url)
                    
                    if not scraped_id:
                        continue
                        
                    # Save to disk
                    self._write_cached_json(f"{scraped_id}.json", cleaned)
                    
                    # Update in-memory Index
                    raw_name = res.get("fullName", "")
                    sanitized = self._sanitize_name(raw_name)
                    
                    wrapper = Person(
                        full_name=sanitized or raw_name,
                        linkedinID=scraped_id,
                        linkedin_profile=cleaned
                    )
                    self.cache[scraped_id] = wrapper
                    if sanitized:
                        self.fuzz_index.append({"full_name": sanitized, "linkedinID": scraped_id})
                        
                    # Mark Success in Registry by removing it completely
                    if scraped_id in self.registry:
                        del self.registry[scraped_id]
                    scraped_ids.add(scraped_id)
                    
                    # Patch the result placeholder with the actual scraped data
                    for r in result:
                        if r.linkedinID == scraped_id:
                            r.linkedin_profile = cleaned
                            r.full_name = wrapper.full_name
                            
                # Mark Failures in Registry
                for sid in to_scrape_ids:
                    if sid not in scraped_ids and sid in self.registry:
                        self.registry[sid]["status"] = "SCRAPE_FAILED"
                        
                self._save_registry()
                
            except Exception as e:
                logger.error(f"Apify batch scrape failed: {e}")
                
        return result



# ---------------------------------------------------------
# Standalone Manual Scraping Routines
# ---------------------------------------------------------

def _get_global_registry_path() -> str:
    import os
    from lib.env import get_env_var
    try:
        repo_dir = get_env_var("REPO_DIR")
        if not repo_dir:
            raise ValueError("REPO_DIR environment variable is empty.")
        return os.path.join(repo_dir, "cache", "linkedin_missing_profiles.json")
    except Exception as e:
        logger.error(f"Failed to resolve global registry path: {e}")
        raise RuntimeError("Missing required environment variable REPO_DIR. Aborting.")


def linkedin_missing_profiles() -> List[Dict[str, Any]]:
    """
    Scans all active datasets, extracts all discovered persons, and runs them through the 
    LinkedInAdapter (with allow_scrape=False) to update the missing registry without making
    external Apify calls. Finally, returns a clean list of entries that require manual scraping.
    """
    from lib.active_dataset import is_active_dataset
    from skills.person_profile.persons_in_dataset import persons_in_dataset
    from lib.slugify import slugify
    import os
    
    logger.info("Scanning for active datasets to identify missing LinkedIn profiles...")
    
    for item in list_dataset_names("startups") + list_dataset_names("community"):
        slug = slugify(item)
        if not is_active_dataset(slug):
            continue
            
        logger.info(f"[{slug}] Extracting persons for LinkedIn registry check...")
        persons = persons_in_dataset(slug)
        if not persons:
            continue
            
        # Instantiate adapter to process cache, fuzzy match, and update registry state
        adapter = LinkedInAdapter(slug)
        # We explicitly disallow scraping to ensure we only hydrate the PENDING registry
        adapter.get_profiles(persons, allow_scrape=False)
        
    # Read the final global registry state
    registry_path = _get_global_registry_path()
    needs_scraping = []
    
    if os.path.exists(registry_path):
        try:
            with open(registry_path, 'r', encoding='utf-8') as f:
                full_registry = json.load(f)
                
            for key, entry in full_registry.items():
                if entry.get("status") in ["PENDING", "URL_NOT_FOUND", "SCRAPE_FAILED"]:
                    needs_scraping.append(entry)
        except Exception as e:
            logger.error(f"Failed to read global missing registry: {e}")
            
    return needs_scraping


def linkedin_bulk_import(file_path: str, dataset: str = None) -> int:
    """
    Accepts a path to a bulk JSON export from the manual web scraper.
    Looks up the profile in the global registry to determine the target dataset.
    If 'dataset' is provided, all profiles are saved to that dataset. 
    If a profile is also in the global registry mapped to a different dataset, 
    it is saved to both. Finally, it purges the pending entry.
    """
    import os
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to read bulk import file '{file_path}': {e}")
        return 0
        
    if not isinstance(data, list):
        data = [data]
        
    registry_path = _get_global_registry_path()
    full_registry = {}
    if os.path.exists(registry_path):
        try:
            with open(registry_path, 'r', encoding='utf-8') as f:
                full_registry = json.load(f)
        except Exception as e:
            logger.warning(f"Could not load global registry: {e}")
            
    success_count = 0
    registry_changed = False
    
    for profile in data:
        # 1. Extract Valid Identifier
        url = profile.get("url", "") or profile.get("linkedinUrl", "")
        ident = extract_linkedin_id(url) if url else profile.get("publicIdentifier", "")
        
        # 2. Handle Explicit Manual Failures (Ghosts)
        if profile.get("error") or profile.get("not_found"):
            ident = ident or profile.get("linkedinID", "")
            if ident and ident in full_registry:
                logger.info(f"Manual scrape failed for {ident}. Marking as DO_NOT_SCRAPE.")
                full_registry[ident]["status"] = "DO_NOT_SCRAPE"
                registry_changed = True
            continue
            
        if not ident:
            logger.warning("Skipping imported manual profile: No valid identifier found.")
            continue
            
        # 3. Lookup Target Dataset
        registry_entry = full_registry.get(ident)
        if not registry_entry:
            # Maybe it's registered under a fuzzy name?
            for key, val in full_registry.items():
                if val.get("linkedinID") == ident:
                    registry_entry = val
                    ident = key # Real key to pop later
                    break
                    
        target_datasets = []
        if dataset:
            target_datasets.append(dataset)
            
        registry_dataset = registry_entry.get("dataset") if registry_entry else None
        if registry_dataset and registry_dataset not in target_datasets:
            target_datasets.append(registry_dataset)
            
        if not target_datasets:
            logger.warning(f"Cannot import profile '{ident}': No matching dataset found in pending registry and no default dataset provided.")
            continue
            
        # 4. Save to Target Dataset(s)
        for target_ds in target_datasets:
            adapter = LinkedInAdapter(target_ds)
            cleaned = adapter._clean_linkedin_data(profile)
            adapter._write_cached_json(f"{ident}.json", cleaned)
            
            # Clean up the adapter's isolated view to avoid overwrites
            if ident in adapter.registry:
                del adapter.registry[ident]
                adapter._save_registry()
                
            logger.info(f"Successfully imported manual profile '{ident}' into dataset '{target_ds}'.")
            
        # 5. Purge from Registry
        if ident in full_registry:
            del full_registry[ident]
            registry_changed = True
            
        success_count += 1
        
    if registry_changed:
        try:
            with open(registry_path, 'w', encoding='utf-8') as f:
                json.dump(full_registry, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to update global missing registry after bulk import: {e}")
            
    logger.info(f"Successfully bulk imported {success_count} manual profiles.")
    return success_count
