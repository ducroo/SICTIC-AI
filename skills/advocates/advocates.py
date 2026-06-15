from typing import List, Optional

from lib.model_config import llm_model
from lib.logger import get_logger
from lib.slugify import slugify
from lib.insights import InsightFile
from skills.config_load.config_load import config_load
from skills.ranking.ranking_persons import ranking_persons
from lib.insights import hydrate_dataset_from_insights
from lib.datasets.ingestion import sync_datasets

logger = get_logger(__name__)

async def advocates(event_name: str, event_description: str, target_members: Optional[List[str]] = None, exclude_members: Optional[List[str]] = None, top_k: int = 10) -> str:
    """
    Provides a ranked list of potential advocates for a given event based on quickselect ranking and LLM refinement.
    """
    event_name_slug = slugify(event_name)
    default_llm = llm_model()
    
    people_dataset = "sictic-members-investor-profile"
    logger.info(f"[{event_name_slug}] Hydrating '{people_dataset}' dataset from 'sictic-members'...")
    await hydrate_dataset_from_insights(
        insight_name="investor_profile",
        source_dataset="sictic-members",
    )
    await sync_datasets([people_dataset], raise_on_error=True)

    try:
        config = config_load()
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
        source_datasets=[people_dataset],
        prompt_key=event_description + objective_template,
    )
    reusable = insight.find_reusable()
    if reusable:
        logger.info(f"[{event_name_slug}] Using cached advocates from {reusable.path}")
        return reusable.content()

    objective = objective_template.replace("{{overview_event}}", event_description)

    # 2. Call ranking_persons Engine
    logger.info(f"[{event_name_slug}] Invoking ranking_persons engine for advocates...")
    
    result = await ranking_persons(
        dataset_name=people_dataset,
        objective=objective,
        query=event_description,
        candidates=target_members,
        optout=exclude_members,
        top_k=top_k
    )
    
    # 3. Output & Persistence
    insight.save(result)
    logger.info(f"[{event_name_slug}] Advocates search complete. Results saved to {insight.path}")

    return result
