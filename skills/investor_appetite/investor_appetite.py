from lib.env import get_env_var
from lib.storage import get_storage
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
    dataset_name_slug = slugify(dataset_name)

    # 1. Input Normalization & Fallback
    if not investors:
        logger.info(f"[{dataset_name}] No investors provided. Fetching all persons from dataset.")
        linkedin_adapter = LinkedInAdapter(dataset_name_slug)
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

    storage = get_storage()
    default_llm = get_env_var("DEFAULT_LLM")
    
    from lib.insight_filepath import get_insight_filepath

    results = {}

    # 2. Parallel Processing
    import asyncio
    from lib.insight_refresh import check_insight_refresh
    
    async def process_investor(investor_name):
        logger.info(f"[{dataset_name}] Processing investor appetite for: {investor_name}")
        
        output_file = get_insight_filepath(
            dataset_name=dataset_name_slug,
            skill_name="investor_appetite",
            model=default_llm,
            identifier=investor_name,
            subdir=True
        )

        # Caching
        needs_refresh, cached_content, matched_file = check_insight_refresh([dataset_name_slug], output_file, default_llm)
        if not needs_refresh:
            results[investor_name] = cached_content
            return

        # Retrieve Person Profile
        try:
            persons = await person_profile(dataset_name=dataset_name, names=investor_name)
            if persons and persons[0].person_profile:
                profile_context = persons[0].person_profile
            else:
                profile_context = "No relevant information found."
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
        # Note: removed a dead second write to undefined `dataset_out_dir` that
        # would have raised NameError. If dual-output is desired, define the
        # second relative path and call storage.write_text again.
        storage.write_text(output_file, appetite_output)
        logger.info(f"[{dataset_name}] Successfully saved investor appetite for '{investor_name}' to {output_file}")
        results[investor_name] = appetite_output

    tasks = [process_investor(inv) for inv in investors_list]
    await asyncio.gather(*tasks)

    # 3. Return
    return results
