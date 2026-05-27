from typing import List, Optional

from lib.logger import get_logger
from lib.storage import get_storage
from skills.config_load.config_load import config_load
from skills.dataset_chat.dataset_search import dataset_search
from lib.ranking_writeup import ranking_writeup
from lib.ranking_top_k import ranking_top_k
from skills.llm_chat.llm_chat import llm_chat

from rapidfuzz import process, fuzz

from lib.slugify import slugify

logger = get_logger(__name__)

# ==========================================
# HELPER FUNCTIONS (Single Responsibility)
# ==========================================

def _resolve_candidates(dataset_name: str, candidates: Optional[List[str]], optout: Optional[List[str]]) -> List[str]:
    """Determines the final list of candidates to rank by fuzzy-matching against available profiles."""
    dataset_dir_rel = f"datasets/{dataset_name}"
    storage = get_storage()
    available_profiles = []
    
    # Files look like "urs-gubser-gemma4-31b-nvfp4.md"
    for filename in storage.list(dataset_dir_rel, suffix=".md"):
        available_profiles.append(filename)

    if not available_profiles:
        raise RuntimeError(f"No profile files found in {dataset_dir_rel}. Cannot rank candidates.")
        
    final_candidates = []
    
    if candidates:
        missing_candidates = []
        for c in candidates:
            c_slug = slugify(c)
            # Use partial_ratio because c_slug ("urs-gubser") is a substring of the filename ("urs-gubser-gemma4.md")
            match = process.extractOne(c_slug, available_profiles, scorer=fuzz.partial_ratio)
            if match and match[1] >= 90:
                final_candidates.append(match[0])
            else:
                missing_candidates.append(c)
                
        if missing_candidates:
            err_msg = f"The following requested candidates could not be found in the dataset: {', '.join(missing_candidates)}"
            logger.error(err_msg)
            raise ValueError(err_msg)
    else:
        final_candidates = available_profiles.copy()
        
    if optout:
        missing_optouts = []
        optout_matches = set()
        for o in optout:
            o_slug = slugify(o)
            match = process.extractOne(o_slug, available_profiles, scorer=fuzz.partial_ratio)
            if match and match[1] >= 90:
                optout_matches.add(match[0])
            else:
                missing_optouts.append(o)
                
        if missing_optouts:
            logger.warning(f"The following optout candidates could not be found in the dataset: {', '.join(missing_optouts)}")
            
        final_candidates = [c for c in final_candidates if c not in optout_matches]
        
    return list(set(final_candidates))

# ==========================================
# MAIN ORCHESTRATOR
# ==========================================

async def people_ranking(
    dataset_name: str = "person_profile",
    objective: str = "", 
    query: str = "",
    candidates: Optional[List[str]] = None, 
    optout: Optional[List[str]] = None, 
    top_k: int = 8
) -> str:
    """
    Core engine to rank SICTIC members using pairwise comparisons.
    Returns the generated markdown report as a string.
    """
    logger.info("Starting people_ranking")

    # 1. Resolve Candidates
    final_candidates = _resolve_candidates(dataset_name, candidates, optout)

    # 2. Semantic Search & Filtering
    cutoff_m = top_k * 4
    logger.info(f"Starting semantic search on dataset '{dataset_name}' with query: '{query[:50]}...'")
    chunks = await dataset_search(
        dataset_name=dataset_name, 
        query=query, 
        max_chunks=cutoff_m * 10
    )
    
    if not chunks:
        err_msg = f"No documents found in dataset {dataset_name} during semantic search."
        logger.error(err_msg)
        raise RuntimeError(err_msg)

    id_to_text = {}
    
    # Filter chunks based on the resolved candidates list
    for c in chunks:
        doc_name = c.document_name
            
        if doc_name in final_candidates:
            if doc_name not in id_to_text:
                id_to_text[doc_name] = ""
            # Aggregate the chunks cleanly into the person's text block
            id_to_text[doc_name] += c.to_md() + "\n\n"
            if len(id_to_text) >= cutoff_m:
                break
                
    if not id_to_text:
        err_msg = "No documents remained after filtering semantic search results against the candidate list."
        logger.error(err_msg)
        raise RuntimeError(err_msg)

    # 3. Execute Find Top K
    logger.info(f"Starting ranking_top_k with {len(id_to_text)} candidates (target top_k: {top_k}).")
    ranked_items, actual_top_k = await ranking_top_k(
        objective=objective,
        all_profiles=id_to_text,
        top_k=top_k
    )

    # 4. Synthesize Final Report
    logger.info(f"Starting ranking_writeup with top {actual_top_k} out of {len(ranked_items)} ranked candidates.")
    result = await ranking_writeup(
        ranked_items=ranked_items,
        objective=objective,
        top_k=actual_top_k
    )

    logger.info(f"[{dataset_name}] people_ranking complete.")
    return result
