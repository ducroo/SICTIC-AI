from typing import List, Optional

from lib.env import get_env_var
from lib.storage import get_storage
from lib.logger import get_logger
from lib.slugify import slugify
from lib.insight_refresh import check_insight_refresh
from skills.config_load.config_load import config_load
from skills.startup_profile.startup_profile import startup_profile
from skills.people_ranking.people_ranking import people_ranking
from lib.dataset_from_insight import dataset_from_insight

logger = get_logger(__name__)

async def expert_search(startup_name: str, target_experts: Optional[List[str]] = None, exclude_experts: Optional[List[str]] = None, top_k: int = 8) -> str:
    """
    Provides a ranked list of potential experts for a given startup based on quickselect ranking and LLM refinement.
    """
    storage = get_storage()
    startup_slug = slugify(startup_name)
    default_llm = get_env_var("DEFAULT_LLM")
    
    from lib.insight_filepath import get_insight_filepath
    out_path = get_insight_filepath(
        dataset_name=startup_slug,
        skill_name="expert_search",
        model=default_llm,
        subdir=False
    )

    # 0. Check cache
    needs_refresh, cached_content, matched_file = check_insight_refresh(["person_profile", startup_slug], out_path, default_llm)
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
    logger.info(f"[{startup_slug}] Hydrating 'person_profile' dataset from 'sictic-members'...")
    await dataset_from_insight(target_dataset="person_profile", source_dataset="sictic-members")

    # 3. Call people_ranking Engine
    logger.info(f"[{startup_slug}] Invoking people_ranking engine for expert search...")
    
    # Ensure candidates and optouts are strictly slugified before passing down
    clean_targets = [slugify(c) for c in target_experts] if target_experts else None
    clean_excludes = [slugify(c) for c in exclude_experts] if exclude_experts else None
    
    result = await people_ranking(
        dataset_name="person_profile",
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
