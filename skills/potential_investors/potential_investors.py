import os
from pathlib import Path
from typing import List, Optional

from lib.env import get_env_var
from lib.logger import get_logger
from lib.slugify import slugify
from lib.insight_refresh import check_insight_refresh
from skills.config_load.config_load import config_load
from skills.startup_profile.startup_profile import startup_profile
from skills.people_ranking.people_ranking import people_ranking

logger = get_logger(__name__)

async def potential_investors(startup_name: str, target_investors: Optional[List[str]] = None, exclude_investors: Optional[List[str]] = None, top_k: int = 8) -> str:
    """
    Provides a ranked list of potential investors for a given startup based on quickselect ranking and LLM refinement.
    """
    gdrive_mount = get_env_var("GDRIVE_MOUNT")
    startup_name_lower = startup_name.lower()
    default_llm = get_env_var("DEFAULT_LLM")
    safe_llm_name = default_llm.split("/")[-1]
    
    gdrive_path = Path(gdrive_mount)
    out_dir = gdrive_path / "insights" / startup_name_lower
    out_dir.mkdir(parents=True, exist_ok=True)
    
    raw_filename_prefix = f"{startup_name_lower}-potential-investors"
    output_filename = f"{slugify(raw_filename_prefix)}-{slugify(safe_llm_name)}.md"
    out_path = out_dir / output_filename
    
    # 0. Check cache
    needs_refresh, cached_content, matched_file = check_insight_refresh(["person_profile", startup_name_lower], str(out_path), safe_llm_name)
    if not needs_refresh:
        logger.info(f"[{startup_name_lower}] Using cached potential investors from {matched_file}")
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
        objective_template = config['potential_investors']['objective']
    except Exception as e:
        logger.error(f"[{startup_name_lower}] Failed to load configuration: {e}")
        raise RuntimeError(f"Failed to load configuration: {e}")

    objective = objective_template.replace("{{startup_profile}}", profile_content)

    # 3. Call people_ranking Engine
    logger.info(f"[{startup_name_lower}] Invoking people_ranking engine for potential investors...")
    
    result = await people_ranking(
        dataset_name="person_profile",
        objective=objective,
        query=profile_content,
        candidates=target_investors,
        optout=exclude_investors,
        top_k=top_k
    )
    
    # 4. Output & Persistence
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(result)
        
    logger.info(f"[{startup_name_lower}] Potential investors search complete. Results saved to {out_path}")
    
    return result
