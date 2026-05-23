from typing import List, Optional

from lib.env import get_env_var
from lib.storage import get_storage
from lib.logger import get_logger
from lib.slugify import slugify
from lib.insight_refresh import check_insight_refresh
from skills.config_load.config_load import config_load
from skills.people_ranking.people_ranking import people_ranking

logger = get_logger(__name__)

async def advocates(event_name: str, event_description: str, target_members: Optional[List[str]] = None, exclude_members: Optional[List[str]] = None, top_k: int = 10) -> str:
    """
    Provides a ranked list of potential advocates for a given event based on quickselect ranking and LLM refinement.
    """
    storage = get_storage(get_env_var("REPOSITORY_DIR"))
    event_name_slug = slugify(event_name)
    safe_llm_name = get_env_var("DEFAULT_LLM").split("/")[-1]

    raw_filename_prefix = f"{event_name_slug}-advocates"
    output_filename = f"{slugify(raw_filename_prefix)}-{slugify(safe_llm_name)}.md"
    out_path = f"insights/sictic_members/advocates/{output_filename}"

    # 0. Check cache
    needs_refresh, cached_content, matched_file = check_insight_refresh(["person_profile", "advocates", event_name_slug], out_path, safe_llm_name)
    if not needs_refresh:
        logger.info(f"[{event_name_slug}] Using cached advocates from {matched_file}")
        return cached_content

    # 1. Config & Objective
    try:
        config = config_load()
        objective_template = config['advocates']['objective']
    except Exception as e:
        logger.error(f"[{event_name_slug}] Failed to load configuration: {e}")
        raise RuntimeError(f"Failed to load configuration: {e}")

    objective = objective_template.replace("{{overview_event}}", event_description)

    # 2. Call people_ranking Engine
    logger.info(f"[{event_name_slug}] Invoking people_ranking engine for advocates...")
    
    result = await people_ranking(
        dataset_name="person_profile",
        objective=objective,
        query=event_description,
        candidates=target_members,
        optout=exclude_members,
        top_k=top_k
    )
    
    # 3. Output & Persistence
    storage.write_text(out_path, result)
    logger.info(f"[{event_name_slug}] Advocates search complete. Results saved to {out_path}")

    return result
