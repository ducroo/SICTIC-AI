import json
from typing import Dict, List, Any, Tuple, Optional
from lib.logger import get_logger
from lib.adapters.web_search import WebSearchAdapter
from lib.adapters.linkedin import LinkedInAdapter
from skills.dataset_chat.dataset_search import dataset_search
from lib.adapters.qdrant import QdrantAdapter
from skills.config_load.config_load import config_load

logger = get_logger(__name__)

async def discover_team(dataset_name: str) -> Tuple[List[dict], str]:
    # 1. Web Search
    query = f"site:linkedin.com/in/ {dataset_name} -intitle:jobs -intitle:directories"
    logger.info(f"[{dataset_name}] Executing Web Search: {query}")
    
    web_search = WebSearchAdapter()
    results = web_search.search(query, num_results=10)
    
    profiles = []
    for r in results:
        profiles.append({"name": r['title'], "url": r['link'], "description": r['snippet']})
        
    cleaned_profiles = []
    public_identifiers = []
    if profiles:
        linkedin_adapter = LinkedInAdapter(cache_rel=f"datasets/{dataset_name.lower()}/linkedin")
        logger.info(f"[{dataset_name}] Fetching full LinkedIn profiles...")
        cleaned_profiles = linkedin_adapter.get_profiles(profiles)
        
        for p in cleaned_profiles:
            username = p.get('publicIdentifier')
            if not username:
                url = p.get('url', '') or p.get('linkedinUrl', '')
                username = linkedin_adapter._extract_username(url)
            if username:
                public_identifiers.append(f"{username}.json")
    else:
        logger.warning(f"[{dataset_name}] No LinkedIn profiles found via Web Search.")

    # 2. Data Room Check
    qdrant = QdrantAdapter(dataset_name)
    dataset_exists = qdrant.dataset_available()
    
    dataroom_context = ""
    if dataset_exists:
        config=config_load()
        queries_text = config["team_profile"]["resume_queries"]
        queries = [q.strip() for q in queries_text.split('\n') if q.strip()]
              
        logger.info(f"[{dataset_name}] Querying data room for context...")
        try:
            chunks = await dataset_search(dataset_name, queries)
            
            # Deduplicate LinkedIn chunks from dataroom chunks
            filtered_chunks = []
            for c in chunks:
                if c.document_name in public_identifiers:
                    continue
                filtered_chunks.append(c)
                
            for c in filtered_chunks:
                dataroom_context += f"Document: {c.document_name} | Page: {c.page_number}\nContent: {c.text}\n\n"
        except Exception as e:
            logger.warning(f"[{dataset_name}] Data room search failed or returned no results: {e}")
            
    # 3. Abort if absolutely nothing found
    if not cleaned_profiles and not dataroom_context:
        raise RuntimeError(f"No LinkedIn profiles and no relevant data room documents found for team profiling of {dataset_name}.")
        
    return cleaned_profiles, dataroom_context