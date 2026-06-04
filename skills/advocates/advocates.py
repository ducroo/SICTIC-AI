from typing import List, Optional

from lib.model_config import llm_model
from lib.storage import get_storage
from lib.logger import get_logger
from lib.slugify import slugify
from lib.insight_refresh import check_insight_refresh
from skills.config_load.config_load import config_load
from skills.ranking.ranking_persons import ranking_persons
from lib.dataset_from_insight import dataset_from_insight

logger = get_logger(__name__)

async def advocates(event_name: str, event_description: str, target_members: Optional[List[str]] = None, exclude_members: Optional[List[str]] = None, top_k: int = 10) -> str:
    """
    Provides a ranked list of potential advocates for a given event based on quickselect ranking and LLM refinement.
    """
    storage = get_storage()
    event_name_slug = slugify(event_name)
    default_llm = llm_model()
    
    from lib.insight_filepath import get_insight_filepath
    out_path = get_insight_filepath(
        dataset_name="sictic-members",
        skill_name="advocates",
        model=default_llm,
        identifier=event_name_slug,
        subdir=True
    )

    # 0. Check cache
    needs_refresh, cached_content, matched_file = check_insight_refresh(["person_profile", "advocates", event_name_slug], out_path)
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

    # 1.5 Hydrate Target Dataset
    people_dataset = "sictic-members-person-profile"
    logger.info(f"[{event_name_slug}] Hydrating '{people_dataset}' dataset from 'sictic-members'...")
    await dataset_from_insight(insight_name="person_profile", source_dataset="sictic-members")

    # 2. Call ranking_persons Engine
    logger.info(f"[{event_name_slug}] Invoking ranking_persons engine for advocates...")
    
    clean_targets = [slugify(c) for c in target_members] if target_members else None
    clean_excludes = [slugify(c) for c in exclude_members] if exclude_members else None
    
    result = await ranking_persons(
        dataset_name=people_dataset,
        objective=objective,
        query=event_description,
        candidates=clean_targets,
        optout=clean_excludes,
        top_k=top_k
    )
    
    # 3. Output & Persistence
    storage.write_text(out_path, result)
    logger.info(f"[{event_name_slug}] Advocates search complete. Results saved to {out_path}")

    return result
