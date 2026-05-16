import os
import re

from lib.env import get_env_var
from lib.logger import get_logger
from lib.insight_refresh import check_insight_refresh
from lib.adapters.linkedin import LinkedInAdapter
from lib.slugify import slugify
from skills.person_profile.person_profile import person_profile
from skills.config_load.config_load import config_load
from skills.llm_chat.llm_chat import llm_chat

logger = get_logger(__name__)

async def investor_appetite(dataset_name: str = "sictic_members", investors: list = None) -> dict:
    """
    Determines the ideal startup profile for one or more investors based on their personal profiles.
    Returns a dictionary mapping investor names to their appetite profile markdown strings.
    """
    dataset_name_lower = dataset_name.lower()
    gdrive_mount = get_env_var("GDRIVE_MOUNT")
    
    # 1. Input Normalization & Fallback
    if not investors:
        logger.info(f"[{dataset_name}] No investors provided. Fetching all persons from dataset.")
        linkedin_cache_dir = os.path.join(gdrive_mount, "datasets", dataset_name_lower, "linkedin")
        linkedin_adapter = LinkedInAdapter(cache_dir=linkedin_cache_dir)
        investors_list = linkedin_adapter.get_all_persons()
    elif isinstance(investors, str):
        investors_list = [investors]
    else:
        investors_list = investors
        
    if not investors_list:
        logger.warning(f"[{dataset_name}] No investors to process.")
        return {}

    # Load configuration once
    try:
        conf = config_load()
        llm_instructions = conf['investor_appetite']['llm_instructions']
        startup_query = conf['startup_profile']['query']
    except KeyError as e:
        logger.error(f"[{dataset_name}] Missing configuration: {e}")
        raise ValueError(f"Missing configuration for investor_appetite or startup_profile: {e}")

    gdrive_mount = get_env_var("GDRIVE_MOUNT")
    default_llm = get_env_var("DEFAULT_LLM")
    safe_llm_name = default_llm.split('/')[-1]
    
    output_dir = os.path.join(gdrive_mount, "insights", dataset_name_lower, "investor_appetite")
    os.makedirs(output_dir, exist_ok=True)
    
    results = {}

    # 2. Parallel Processing
    import asyncio
    from lib.insight_refresh import check_insight_refresh
    
    async def process_investor(investor_name):
        logger.info(f"[{dataset_name}] Processing investor appetite for: {investor_name}")
        raw_filename_prefix = f"{investor_name}-investor-appetite"
        output_filename = f"{slugify(raw_filename_prefix)}-{slugify(safe_llm_name)}.md"
        output_file = os.path.join(output_dir, output_filename)
        
        # Caching
        needs_refresh, cached_content, matched_file = check_insight_refresh([dataset_name_lower], output_file, safe_llm_name)
        if not needs_refresh:
            results[investor_name] = cached_content
            return
                
        # Retrieve Person Profile
        try:
            profile_context = await person_profile(name=investor_name, dataset_name=dataset_name)
        except Exception as e:
            logger.error(f"[{dataset_name}] Failed to fetch person profile for {investor_name}: {e}")
            results[investor_name] = f"Error: Could not retrieve person profile. ({e})"
            return
            
        # LLM Generation
        prompt = f"Context: {profile_context}\n\nInstructions: {llm_instructions}\n\nTarget Dimensions (from Startup Profile Query): {startup_query}"
        try:
            appetite_output = await llm_chat(prompt=prompt)
        except Exception as e:
            logger.error(f"[{dataset_name}] LLM generation failed for {investor_name}: {e}")
            results[investor_name] = f"Error: LLM generation failed. ({e})"
            return
            
        if not appetite_output or not appetite_output.strip():
            logger.error(f"[{dataset_name}] LLM returned empty response for {investor_name}.")
            results[investor_name] = "Error: LLM returned empty response."
            return
            
        # Output Generation
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(appetite_output)
            
        dataset_output_file = os.path.join(dataset_out_dir, output_filename)
        with open(dataset_output_file, 'w', encoding='utf-8') as f:
            f.write(appetite_output)
            
        logger.info(f"[{dataset_name}] Successfully saved investor appetite for '{investor_name}' to {output_file} and {dataset_output_file}")
        results[investor_name] = appetite_output

    tasks = [process_investor(inv) for inv in investors_list]
    await asyncio.gather(*tasks)

    # 3. Return
    return results