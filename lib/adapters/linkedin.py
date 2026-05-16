import json
import re
import unicodedata
try:
    from rapidfuzz import process, fuzz
except ImportError:
    process = None
    fuzz = None
from lib.logger import get_logger
from lib.storage import get_storage
from lib.adapters.apify import ApifyAdapter
from lib.adapters.web_search import WebSearchAdapter
from lib.slugify import slugify

logger = get_logger(__name__)

class LinkedInAdapter:
    def __init__(self, cache_rel: str):
        """
        Stores cached LinkedIn JSON under `cache_rel` (a storage-relative path,
        e.g. "datasets/sictic_members/linkedin"). All reads/writes go through
        the storage abstraction, so the same code works under both
        LocalStorage (rclone-mount mode) and GoogleDriveStorage (API mode).
        """
        self.cache_rel = cache_rel.strip("/")
        self.storage = get_storage()
        self.apify = ApifyAdapter()
        self.google = WebSearchAdapter()
        self._cache_index = None

    def _list_cached_json(self) -> list[str]:
        if not self.storage.exists(self.cache_rel):
            return []
        return [f for f in self.storage.list(self.cache_rel, suffix=".json")]

    def _read_cached_json(self, filename: str) -> dict | None:
        try:
            return json.loads(self.storage.read_text(f"{self.cache_rel}/{filename}"))
        except Exception as e:
            logger.error(f"Failed to read cached LinkedIn JSON {filename}: {e}")
            return None

    def _write_cached_json(self, filename: str, data: dict) -> None:
        self.storage.write_text(f"{self.cache_rel}/{filename}", json.dumps(data, indent=2))

        
    def _clean_linkedin_data(self, data: dict) -> dict:
        """Aggressively strips unnecessary objects, IDs, URLs, and empty fields."""
        keys_to_remove = [
            "certifications", "recommendations", "courses", "languages", 
            "volunteering", "projects", "peopleAlsoViewed", "similarProfiles",
            "honors", "testScores", "publications", "articles", "skills"
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

    def _extract_username(self, url: str) -> str:
        """Extracts the username part from a LinkedIn URL."""
        if not url:
            return ""
        # Remove trailing slash and query params
        url = url.split('?')[0].strip('/')
        # Extract the part after /in/ or /pub/
        match = re.search(r'linkedin\.com/(?:in|pub)/([^/]+)', url, re.IGNORECASE)
        if match:
            return match.group(1).lower()
        return slugify(url)
        
    def _build_cache_index(self):
        """Loads fullName from all JSON files in the cache to enable fuzzy matching."""
        if self._cache_index is not None:
            return

        self._cache_index = []
        for filename in self._list_cached_json():
            data = self._read_cached_json(filename)
            if not data:
                continue
            first_name = data.get("firstName", "").strip()
            last_name = data.get("lastName", "").strip()
            full_name = f"{first_name} {last_name}".strip()
            if not full_name:
                full_name = data.get("fullName", "").strip()

            if full_name:
                # Remove emojis for cleaner matching
                full_name = ''.join(c for c in full_name if not unicodedata.category(c).startswith('So')).strip()
                self._cache_index.append({
                    "filename": filename,
                    "fullName": full_name
                })

    def get_all_persons(self) -> list[str]:
        """
        Iterates through all JSON profiles in the cache directory, extracts the full names,
        cleans emojis, and returns a sorted list of names.
        """
        all_persons = []
        for filename in self._list_cached_json():
            data = self._read_cached_json(filename)
            if not data:
                continue
            first_name = data.get("firstName", "").strip()
            last_name = data.get("lastName", "").strip()
            full_name = f"{first_name} {last_name}".strip()
            if not full_name:
                full_name = data.get("fullName", "").strip()

            if full_name:
                # Remove emojis for cleaner matching
                full_name = ''.join(c for c in full_name if not unicodedata.category(c).startswith('So')).strip()
                if full_name:
                    all_persons.append(full_name)

        all_persons.sort()
        return all_persons

    def _fuzzy_match_in_cache(self, name: str) -> str | None:
        """Finds the best matching profile in cache using RapidFuzz."""
        if not name or process is None or fuzz is None:
            return None
            
        self._build_cache_index()
        
        if not self._cache_index:
            return None
            
        profile_names = [p["fullName"] for p in self._cache_index]
        matches = process.extract(name, profile_names, scorer=fuzz.token_sort_ratio, limit=1)
        
        if matches:
            best_match, score, index = matches[0]
            if score >= 85:  # Safe threshold for name matching
                matched_filename = self._cache_index[index]["filename"]
                logger.info(f"Fuzzy match found for '{name}': {best_match} ({matched_filename}) with score {score}")
                return matched_filename
            else:
                logger.info(f"Best fuzzy match for '{name}' was {best_match} but score {score} was below threshold.")
                
        return None

    def get_filename_for_profile(self, profile: dict, fallback_name: str = "") -> str:
        """Determines the unique JSON filename for a given profile dictionary."""
        ident = profile.get('publicIdentifier', '')
        if not ident:
            url = profile.get('url', '') or profile.get('linkedinUrl', '')
            ident = self._extract_username(url)
        if not ident:
            full_name = profile.get('fullName', '') or fallback_name
            ident = slugify(full_name) if full_name else 'unknown'
        return f"{ident}.json"

    def get_profiles(self, persons: list[dict]) -> list[dict]:
        """
        Takes a list of person dictionaries (e.g. {"name": "...", "url": "...", "description": "..."}).
        Returns a list of profile dictionaries.
        """
        profiles = []
        missing_urls = []
        
        for person in persons:
            name = person.get("name", "")
            url = person.get("url", "")
            description = person.get("description", "")
            
            if not name and not url:
                continue
                
            # Attempt to find in cache by URL first
            cache_filename = None
            if url:
                username = self._extract_username(url)
                if username and self.storage.exists(f"{self.cache_rel}/{username}.json"):
                    cache_filename = f"{username}.json"

            # If not found by URL, attempt to cross-check by fuzzy matching name
            if not cache_filename and name:
                cache_filename = self._fuzzy_match_in_cache(name)

            if cache_filename:
                cached = self._read_cached_json(cache_filename)
                if cached is not None:
                    logger.info(f"Loaded {name or url} from cache ({self.cache_rel}/{cache_filename}).")
                    profiles.append(cached)
                    continue

            if True:
                if url and "linkedin.com/in/" in url.lower():
                    final_url = url
                else:
                    search_query = f"{name} {description}".strip()
                    logger.info(f"Converting person '{search_query}' to LinkedIn URL...")
                    final_url = self._extract_linkedin_url(search_query)
                    if not final_url:
                        logger.warning(f"Could not find LinkedIn URL for '{search_query}'.")
                        continue
                        
                identifier = name if name else final_url
                missing_urls.append((identifier, final_url))
                
        if missing_urls:
            urls_to_fetch = list(set([u for _, u in missing_urls]))
            try:
                results = self.apify.run_actor(
                    actor_id="dev_fusion/Linkedin-Profile-Scraper", 
                    run_input={"urls": urls_to_fetch}
                )
                
                # Match results and save to cache strictly by LinkedIn username
                for res in results:
                    cleaned_res = self._clean_linkedin_data(res)
                    profiles.append(cleaned_res)

                    filename = self.get_filename_for_profile(cleaned_res, res.get('fullName', 'unknown'))
                    self._write_cached_json(filename, cleaned_res)
            except Exception as e:
                logger.error(f"Failed to fetch profiles via Apify: {e}")
                
        return profiles

    def bulk_import(self, profiles: list[dict]) -> int:
        """
        Takes a list of LinkedIn profile dictionaries and saves them directly into the cache.
        Returns the number of profiles successfully imported.
        """
        success_count = 0
        for profile in profiles:
            try:
                cleaned_profile = self._clean_linkedin_data(profile)
                filename = self.get_filename_for_profile(cleaned_profile, profile.get('fullName', ''))

                if not filename or filename == 'unknown.json':
                    logger.warning("Skipping bulk import for profile without valid URL, publicIdentifier or name.")
                    continue

                self._write_cached_json(filename, cleaned_profile)
                success_count += 1
            except Exception as e:
                logger.error(f"Failed to import profile: {e}")

        logger.info(f"Successfully bulk imported {success_count} profiles into the cache.")
        return success_count