from typing import List, Optional

from lib.model_config import llm_model
from lib.infrastructure.logging import get_logger
from lib.slugify import slugify
from lib.insights import InsightFile, InsightResult
from lib.infrastructure.configuration import (
    config_cache_key,
    load_repository_config,
)
from skills.ranking.ranking_persons import ranking_persons

logger = get_logger(__name__)

async def advocates(event_name: str, event_description: str, target_members: Optional[List[str]] = None, exclude_members: Optional[List[str]] = None, top_k: int = 10) -> InsightResult:
    """
    Provides a ranked list of potential advocates for a given event based on quickselect ranking and LLM refinement.
    """
    event_name_slug = slugify(event_name)
    default_llm = llm_model()
    
    try:
        config = load_repository_config()
        objective_template = config['advocates']['objective']
    except Exception as e:
        logger.error(f"[{event_name_slug}] Failed to load configuration: {e}")
        raise RuntimeError(f"Failed to load configuration: {e}")

    insight = InsightFile(
        dataset="sictic-members",
        skill="advocates",
        model=default_llm,
        identifier=event_name_slug,
        subdir=True,
        config_key=config_cache_key(
            config["advocates"],
            config.get("ranking_top_k", {}),
            config.get("ranking_rationale", {}),
            {
                "event_description": event_description,
                "target_members": target_members,
                "exclude_members": exclude_members,
                "top_k": top_k,
            },
        ),
    )
    objective = objective_template.replace("{{overview_event}}", event_description)

    # 2. Call ranking_persons Engine
    logger.info(f"[{event_name_slug}] Invoking ranking_persons engine for advocates...")
    
    result = await ranking_persons(
        source_datasets=["sictic-members"],
        skill="investor_profile",
        objective=objective,
        candidates=target_members,
        optout=exclude_members,
        top_k=top_k
    )
    
    # 3. Output & Persistence
    insight.save(result)
    logger.info(f"[{event_name_slug}] Advocates search complete. Results saved to {insight.path}")

    return [insight]
