from typing import List, Optional

from skills.config_load.config_load import config_load
from lib.logger import get_logger

from lib.linkedin import LinkedInResolver
from lib.insights import InsightFile
from lib.slugify import slugify
from skills.suggested_startups.core.llm_processor import compile_startup_profiles, process_single_investor
from skills.investor_profile.investor_profile import investor_profile, read_investor_profiles
from lib.datasets.ingestion import sync_datasets
from lib.datasets.paths import list_dataset_names

logger = get_logger(__name__)

async def suggested_startups(dataset_name: str = "sictic_members", startups: Optional[List[str]] = None, investors: Optional[List[str]] = None, max_startups: int = 5) -> str:
    """
    Rank a provided list of startups against a list of investors by matching 
    startup value propositions with investor professional backgrounds and interests.
    Outputs a distinct file per investor in the suggested_startups folder.
    """
    from lib.model_config import llm_model
    
    dataset_slug = slugify(dataset_name)
    
    # Resolve default investors from the community LinkedIn cache.
    if not investors:
        linkedin_resolver = LinkedInResolver(dataset_slug)
        investors = linkedin_resolver.get_all_persons()
        
    # Resolve default startups dynamically using config
    if not startups:
        config = config_load()
        bulk_config = config.get("bulk_refresh", {})
        community_datasets = [slugify(s) for s in bulk_config.get("community_datasets", ["sictic-members"])]
        ignore_datasets = [slugify(s) for s in bulk_config.get("ignore_datasets", ["investor-profile", "person-profile"])]

        discovered = []
        for item in list_dataset_names("startups"):
            item_slug = slugify(item)
            if item_slug not in community_datasets and item_slug not in ignore_datasets:
                discovered.append(item)
        startups = discovered
    
    if not startups or not investors:
        raise ValueError("Startups and investors lists cannot be empty after default resolution.")

    try:
        conf = config_load()
        prompt_template = conf['suggested_startups']['suggested_startups_prompt']
    except KeyError as e:
        logger.error(f"[{dataset_name}] Missing configuration: {e}")
        raise ValueError(f"Missing configuration for suggested_startups: {e}")

    default_llm = llm_model()

    # Filter investors whose cache is already up-to-date
    investors_to_process = []
    datasets_to_check = [dataset_slug] + [slugify(s) for s in startups]
    await sync_datasets(datasets_to_check, raise_on_error=True)

    for investor in investors:
        insight = InsightFile(
            dataset=dataset_slug,
            skill="suggested_startups",
            model=default_llm,
            identifier=investor,
            subdir=True,
            source_datasets=datasets_to_check,
            prompt_key=prompt_template,
        )
        reusable = insight.find_reusable()
        if reusable:
            logger.info(f"[{dataset_name}] Skipping {investor}: Cache up to date.")
            continue
            
        investors_to_process.append((investor, insight))
        
    if not investors_to_process:
        logger.info(f"[{dataset_name}] All investor suggestions are up to date. Exiting.")
        return "All up to date."

    compiled_startups = await compile_startup_profiles(startups)
    
    names_to_process = [inv for inv, _ in investors_to_process]
    logger.info(f"[{dataset_name}] Batch fetching investor profiles for {len(names_to_process)} investors...")
    await investor_profile(source_dataset=dataset_slug)
    investor_profiles_dict = read_investor_profiles(dataset_slug, names_to_process)
    
    import asyncio

    async def process_inv(investor, insight):
        logger.info(f"[{dataset_name}] Processing investor: {investor}")
        profile_text = investor_profiles_dict.get(investor)
        
        if not profile_text:
            logger.error(f"[{dataset_name}] No detailed profile available for {investor}. Skipping.")
            return f"No results for {investor}"
            
        new_lines = await process_single_investor(investor, profile_text, compiled_startups, prompt_template, max_startups)
        
        if new_lines:
            header = f"# Startup Suggestions for {investor}\n\n| Startup | Rationale |\n|---|---|\n"
            content = header + "\n".join(new_lines)
            insight.save(content)
            logger.info(f"[{dataset_name}] Saved suggestions for {investor} to {insight.path}")
            return f"Processed {investor}"
        return f"No results for {investor}"
        
    tasks = [process_inv(inv, insight) for inv, insight in investors_to_process]
    results = await asyncio.gather(*tasks)

    logger.info(f"[{dataset_name}] Successfully finished suggested_startups.")
    
    return "\n".join(results)
