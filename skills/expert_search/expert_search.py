from typing import List, Optional

from lib.model_config import llm_model
from lib.storage import get_storage
from lib.logger import get_logger
from lib.slugify import slugify
from lib.insight_refresh import check_insight_refresh
from skills.config_load.config_load import config_load
from skills.startup_profile.startup_profile import startup_profile
from skills.ranking.ranking_persons import ranking_persons
from lib.dataset_from_insight import dataset_from_insight

logger = get_logger(__name__)

async def expert_search(startup_name: str, target_experts: Optional[List[str]] = None, exclude_experts: Optional[List[str]] = None, top_k: int = 8) -> str:
    """
    Provides a ranked list of potential experts for a given startup based on quickselect ranking and LLM refinement.
    """
    storage = get_storage()
    startup_slug = slugify(startup_name)
    from lib.startup_data_sources import ensure_startup_dataset

    status = await ensure_startup_dataset(startup_slug)
    startup_slug = status.dataset_slug
    startup_name = startup_slug
    default_llm = llm_model()
    
    from lib.insight_filepath import get_insight_filepath
    out_path = get_insight_filepath(
        dataset_name=startup_slug,
        skill_name="expert_search",
        model=default_llm,
        subdir=False
    )

    # 0. Check cache
    needs_refresh, cached_content, matched_file = check_insight_refresh(["investor_profile", startup_slug], out_path)
    if not needs_refresh:
        logger.info(f"[{startup_slug}] Using cached expert search from {matched_file}")
        return cached_content

    # 1. Fetch Startup Profile
    logger.info(f"[{startup_slug}] Fetching startup profile...")
    try:
        profile_content, _ = await startup_profile(startup_name)
    except Exception as e:
        logger.error(f"[{startup_slug}] Failed to generate/fetch startup profile: {e}")
        raise RuntimeError(f"Failed to generate/fetch startup profile: {e}")

    # 2. Config & Objective
    try:
        config = config_load()
        objective_template = config['expert_search']['objective']
    except Exception as e:
        logger.error(f"[{startup_slug}] Failed to load configuration: {e}")
        raise RuntimeError(f"Failed to load configuration: {e}")

    objective = objective_template.replace("{{startup_profile}}", profile_content)

    # 2.5 Hydrate Target Dataset
    people_dataset = "sictic-members-investor-profile"
    logger.info(f"[{startup_slug}] Hydrating '{people_dataset}' dataset from 'sictic-members'...")
    await dataset_from_insight(insight_name="investor_profile", source_dataset="sictic-members")

    # 3. Call ranking_persons Engine
    logger.info(f"[{startup_slug}] Invoking ranking_persons engine for expert search...")
    
    # Ensure candidates and optouts are strictly slugified before passing down
    clean_targets = [slugify(c) for c in target_experts] if target_experts else None
    clean_excludes = [slugify(c) for c in exclude_experts] if exclude_experts else None
    
    result = await ranking_persons(
        dataset_name=people_dataset,
        objective=objective,
        query=profile_content,
        candidates=clean_targets,
        optout=clean_excludes,
        top_k=top_k
    )
    
    # 4. Output & Persistence
    storage.write_text(out_path, result)
    logger.info(f"[{startup_slug}] Expert search complete. Results saved to {out_path}")

    return result
