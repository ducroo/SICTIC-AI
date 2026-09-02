from typing import List, Optional

from lib.model_config import llm_model
from lib.infrastructure.logging import get_logger
from lib.slugify import slugify
from lib.insights import InsightFile, InsightResult
from lib.infrastructure.configuration import (
    config_cache_key,
    load_repository_config,
)
from skills.startup_profile.startup_profile import startup_profile
from skills.ranking.ranking_persons import ranking_persons

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
    
    try:
        config = load_repository_config()
        objective_template = config['expert_search']['objective']
    except Exception as e:
        logger.error(f"[{startup_slug}] Failed to load configuration: {e}")
        raise RuntimeError(f"Failed to load configuration: {e}")
    insight = InsightFile(
        dataset=startup_slug,
        skill="expert_search",
        model=default_llm,
        config_key=config_cache_key(
            config["expert_search"],
            config.get("ranking_top_k", {}),
            config.get("ranking_rationale", {}),
            config.get("structured_output", {}),
            {
                "target_experts": target_experts,
                "exclude_experts": exclude_experts,
                "top_k": top_k,
            },
        ),
    )
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
        source_datasets=["sictic-members"],
        skill="investor_profile",
        objective=objective,
        candidates=target_experts,
        optout=exclude_experts,
        top_k=top_k
    )
    
    # 4. Output & Persistence
    insight.save(result)
    logger.info(f"[{startup_slug}] Expert search complete. Results saved to {insight.path}")

    return [insight]
