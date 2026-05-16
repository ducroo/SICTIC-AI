from typing import List, Optional

from skills.config_load.config_load import config_load
from skills.utils.logger import get_logger

from skills.utils.adapters.linkedin import LinkedInAdapter
from skills.utils.insight_refresh import check_insight_refresh
from skills.utils.slugify import slugify
from skills.utils.storage import get_storage
from skills.suggest_startups.core.llm_processor import compile_startup_profiles, process_single_investor
from skills.utils.member_profile import member_profile

logger = get_logger(__name__)

async def suggest_startups(dataset_name: str = "sictic_members", startups: Optional[List[str]] = None, investors: Optional[List[str]] = None, max_startups: int = 5) -> str:
    """
    Rank a provided list of startups against a list of investors by matching 
    startup value propositions with investor professional backgrounds and interests.
    Outputs a distinct file per investor in the suggest_startups folder.
    """
    from skills.utils.env import get_env_var

    storage = get_storage()

    # Resolve default investors using LinkedInAdapter for the community dataset
    if not investors:
        linkedin_cache_dir = str(storage.local_path(f"datasets/{dataset_name.lower()}/linkedin"))
        linkedin_adapter = LinkedInAdapter(cache_dir=linkedin_cache_dir)
        investors = linkedin_adapter.get_all_persons()

    # Resolve default startups dynamically using config
    if not startups:
        config = config_load()
        bulk_config = config.get("bulk_refresh", {})
        community_datasets = [s.lower() for s in bulk_config.get("community_datasets", ["sictic_members"])]
        ignore_datasets = [s.lower() for s in bulk_config.get("ignore_datasets", ["investor_appetite", "person_profile"])]

        discovered = []
        if storage.exists("datasets"):
            for item in storage.list("datasets"):
                item_lower = item.lower()
                if storage.is_dir(f"datasets/{item}"):
                    if item_lower not in community_datasets and item_lower not in ignore_datasets:
                        discovered.append(item)
        startups = discovered
    
    if not startups or not investors:
        raise ValueError("Startups and investors lists must not be empty after default resolution.")

    try:
        conf = config_load()
        prompt_template = conf['suggest_startups']['suggest_startups_prompt']
    except KeyError as e:
        logger.error(f"[{dataset_name}] Missing configuration: {e}")
        raise ValueError(f"Missing configuration for suggest_startups: {e}")

    safe_llm_name = get_env_var("DEFAULT_LLM").split('/')[-1]

    out_dir = f"insights/{dataset_name.lower()}/suggest_startups"

    # Filter investors whose cache is already up-to-date
    investors_to_process = []
    datasets_to_check = [dataset_name.lower()] + [s.lower() for s in startups]

    for investor in investors:
        raw_filename_prefix = f"{investor}-suggest-startups"
        filename = f"{slugify(raw_filename_prefix)}-{slugify(safe_llm_name)}.md"
        output_file = f"{out_dir}/{filename}"
        
        needs_refresh, cached_content, matched_file = check_insight_refresh(datasets_to_check, output_file, safe_llm_name)
        if not needs_refresh:
            logger.info(f"[{dataset_name}] Skipping {investor}: Cache up to date.")
            continue
            
        investors_to_process.append((investor, output_file))
        
    if not investors_to_process:
        logger.info(f"[{dataset_name}] All investor suggestions are up to date. Exiting.")
        return "All up to date."

    compiled_startups = await compile_startup_profiles(startups)
    
    names_to_process = [inv for inv, _ in investors_to_process]
    logger.info(f"[{dataset_name}] Batch fetching investor appetites for {len(names_to_process)} investors...")
    investor_profiles_dict = await member_profile("investor_profile", names_to_process)
    
    import asyncio

    async def process_inv(investor, output_file):
        logger.info(f"[{dataset_name}] Processing investor: {investor}")
        profile_text = investor_profiles_dict.get(investor)
        
        if not profile_text:
            logger.error(f"[{dataset_name}] No detailed profile available for {investor}. Skipping.")
            return f"No results for {investor}"
            
        new_lines = await process_single_investor(investor, profile_text, compiled_startups, prompt_template, max_startups)
        
        if new_lines:
            header = f"# Startup Suggestions for {investor}\n\n| Startup | Rationale |\n|---|---|\n"
            content = header + "\n".join(new_lines)
            storage.write_text(output_file, content)
            logger.info(f"[{dataset_name}] Saved suggestions for {investor} to {output_file}")
            return f"Processed {investor}"
        return f"No results for {investor}"
        
    tasks = [process_inv(inv, out_file) for inv, out_file in investors_to_process]
    results = await asyncio.gather(*tasks)

    logger.info(f"[{dataset_name}] Successfully finished suggest_startups.")
    
    return "\n".join(results)
