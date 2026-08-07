from typing import List, Optional

from lib.model_config import llm_model
from lib.logger import get_logger
from lib.slugify import slugify
from lib.insights import InsightFile, InsightResult
from skills.config_load.config_load import config_load
from skills.startup_profile.startup_profile import startup_profile
from skills.ranking.ranking_persons import ranking_persons
from lib.insights import hydrate_dataset_from_insights
from lib.datasets.ingestion import sync_datasets

logger = get_logger(__name__)

async def expert_search(startup_name: str, target_experts: Optional[List[str]] = None, exclude_experts: Optional[List[str]] = None, top_k: int = 8) -> InsightResult:
    """
    Provides a ranked list of potential experts for a given startup based on quickselect ranking and LLM refinement.
    """
    startup_slug = slugify(startup_name)
    from lib.startups.sources import ensure_startup_dataset

    status = await ensure_startup_dataset(startup_slug)
    startup_slug = status.dataset_slug
    startup_name = startup_slug
    default_llm = llm_model()
    
    people_dataset = "sictic-members-investor-profile"
    logger.info(f"[{startup_slug}] Hydrating '{people_dataset}' dataset from 'sictic-members'...")
    await hydrate_dataset_from_insights(
        insight_name="investor_profile",
        source_dataset="sictic-members",
    )
    await sync_datasets(
        [people_dataset, startup_slug],
        raise_on_error=True,
    )

    try:
        objective_template = config_load()['expert_search']['objective']
    except Exception as e:
        logger.error(f"[{startup_slug}] Failed to load configuration: {e}")
        raise RuntimeError(f"Failed to load configuration: {e}")
    insight = InsightFile(
        dataset=startup_slug,
        skill="expert_search",
        model=default_llm,
        source_datasets=[people_dataset, startup_slug],
        prompt_key=objective_template,
    )
    reusable = insight.find_reusable()
    if reusable:
        logger.info(f"[{startup_slug}] Using cached expert search from {reusable.path}")
        return [reusable]

    # 1. Fetch Startup Profile
    logger.info(f"[{startup_slug}] Fetching startup profile...")
    try:
        [profile_insight] = await startup_profile(startup_name)
        profile_content = profile_insight.content()
    except Exception as e:
        logger.error(f"[{startup_slug}] Failed to generate/fetch startup profile: {e}")
        raise RuntimeError(f"Failed to generate/fetch startup profile: {e}")

    objective = objective_template.replace("{{startup_profile}}", profile_content)

    # 3. Call ranking_persons Engine
    logger.info(f"[{startup_slug}] Invoking ranking_persons engine for expert search...")
    
    result = await ranking_persons(
        dataset_name=people_dataset,
        objective=objective,
        query=profile_content,
        candidates=target_experts,
        optout=exclude_experts,
        top_k=top_k
    )
    
    # 4. Output & Persistence
    insight.save(result)
    logger.info(f"[{startup_slug}] Expert search complete. Results saved to {insight.path}")

    return [insight]
