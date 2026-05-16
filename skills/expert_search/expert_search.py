from typing import List, Optional

from lib.env import get_env_var
from lib.storage import get_storage
from lib.logger import get_logger
from lib.slugify import slugify
from lib.insight_refresh import check_insight_refresh
from skills.config_load.config_load import config_load
from skills.startup_profile.startup_profile import startup_profile
from skills.people_ranking.people_ranking import people_ranking

logger = get_logger(__name__)

async def expert_search(startup_name: str, target_experts: Optional[List[str]] = None, exclude_experts: Optional[List[str]] = None, top_k: int = 8) -> str:
    """
    Provides a ranked list of potential experts for a given startup based on quickselect ranking and LLM refinement.
    """
    storage = get_storage()
    startup_name_lower = startup_name.lower()
    safe_llm_name = get_env_var("DEFAULT_LLM").split("/")[-1]

    raw_filename_prefix = f"{startup_name_lower}-expert-search"
    output_filename = f"{slugify(raw_filename_prefix)}-{slugify(safe_llm_name)}.md"
    out_path = f"insights/{startup_name_lower}/{output_filename}"

    # 0. Check cache
    needs_refresh, cached_content, matched_file = check_insight_refresh(["person_profile", startup_name_lower], out_path, safe_llm_name)
    if not needs_refresh:
        logger.info(f"[{startup_name_lower}] Using cached expert search from {matched_file}")
        return cached_content

    # 1. Fetch Startup Profile
    logger.info(f"[{startup_name_lower}] Fetching startup profile...")
    try:
        profile_content, _ = await startup_profile(startup_name)
    except Exception as e:
        logger.error(f"[{startup_name_lower}] Failed to generate/fetch startup profile: {e}")
        raise RuntimeError(f"Failed to generate/fetch startup profile: {e}")

    # 2. Config & Objective
    try:
        config = config_load()
        objective_template = config['expert_search']['objective']
    except Exception as e:
        logger.error(f"[{startup_name_lower}] Failed to load configuration: {e}")
        raise RuntimeError(f"Failed to load configuration: {e}")

    objective = objective_template.replace("{{startup_profile}}", profile_content)

    # 3. Call people_ranking Engine
    logger.info(f"[{startup_name_lower}] Invoking people_ranking engine for expert search...")
    
    result = await people_ranking(
        dataset_name="person_profile",
        objective=objective,
        query=profile_content,
        candidates=target_experts,
        optout=exclude_experts,
        top_k=top_k
    )
    
    # 4. Output & Persistence
    storage.write_text(out_path, result)
    logger.info(f"[{startup_name_lower}] Expert search complete. Results saved to {out_path}")

    return result
