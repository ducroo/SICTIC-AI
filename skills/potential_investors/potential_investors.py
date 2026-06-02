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

async def potential_investors(startup_name: str, target_investors: Optional[List[str]] = None, exclude_investors: Optional[List[str]] = None, top_k: int = 16) -> str:
    """
    Provides a ranked list of potential investors for a given startup based on quickselect ranking and LLM refinement.
    """
    storage = get_storage()
    startup_slug = slugify(startup_name)
    default_llm = llm_model()

    from lib.insight_filepath import get_insight_filepath
    out_path = get_insight_filepath(
        dataset_name=startup_slug,
        skill_name="potential_investors",
        model=default_llm,
        subdir=False
    )

    # 0. Check cache
    needs_refresh, cached_content, matched_file = check_insight_refresh(["person_profile", startup_slug], out_path)
    if not needs_refresh:
        logger.info(f"[{startup_slug}] Using cached potential investors from {matched_file}")
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
        objective_template = config['potential_investors']['objective']
    except Exception as e:
        logger.error(f"[{startup_slug}] Failed to load configuration: {e}")
        raise RuntimeError(f"Failed to load configuration: {e}")

    objective = objective_template.replace("{{startup_profile}}", profile_content)

    # 2.5 Hydrate Target Dataset
    logger.info(f"[{startup_slug}] Hydrating 'person_profile' dataset from 'sictic-members'...")
    await dataset_from_insight(target_dataset="person_profile", source_dataset="sictic-members")

    # 3. Call ranking_persons Engine
    logger.info(f"[{startup_slug}] Invoking ranking_persons engine for potential investors...")
    
    clean_targets = [slugify(c) for c in target_investors] if target_investors else None
    clean_excludes = [slugify(c) for c in exclude_investors] if exclude_investors else None
    
    result = await ranking_persons(
        dataset_name="person_profile",
        objective=objective,
        query=profile_content,
        candidates=clean_targets,
        optout=clean_excludes,
        top_k=top_k
    )
    
    # 4. Output & Persistence
    storage.write_text(out_path, result)
    logger.info(f"[{startup_slug}] Potential investors search complete. Results saved to {out_path}")

    return result
