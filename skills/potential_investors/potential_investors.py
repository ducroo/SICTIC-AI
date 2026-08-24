from typing import List, Optional

from lib.model_config import llm_model
from lib.logger import get_logger
from lib.slugify import slugify
from lib.insights import InsightFile, InsightResult
from skills.config_load.config_load import config_key, config_load
from skills.startup_profile.startup_profile import startup_profile
from skills.ranking.ranking_persons import ranking_persons

logger = get_logger(__name__)

async def potential_investors(startup_name: str, target_investors: Optional[List[str]] = None, exclude_investors: Optional[List[str]] = None, top_k: int = 16) -> InsightResult:
    """
    Provides a ranked list of potential investors for a given startup based on quickselect ranking and LLM refinement.
    """
    startup_slug = slugify(startup_name)
    from lib.startups.sources import ensure_startup_dataset

    status = await ensure_startup_dataset(startup_slug)
    startup_slug = status.dataset_slug
    startup_name = startup_slug
    default_llm = llm_model()

    try:
        config = config_load()
        objective_template = config['potential_investors']['objective']
    except Exception as e:
        logger.error(f"[{startup_slug}] Failed to load configuration: {e}")
        raise RuntimeError(f"Failed to load configuration: {e}")
    insight = InsightFile(
        dataset=startup_slug,
        skill="potential_investors",
        model=default_llm,
        config_key=config_key(
            config["potential_investors"],
            config.get("ranking_top_k", {}),
            config.get("ranking_rationale", {}),
            config.get("structured_output", {}),
            {
                "target_investors": target_investors,
                "exclude_investors": exclude_investors,
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
    logger.info(f"[{startup_slug}] Invoking ranking_persons engine for potential investors...")
    
    result = await ranking_persons(
        source_datasets=["sictic-members"],
        skill="investor_profile",
        objective=objective,
        candidates=target_investors,
        optout=exclude_investors,
        top_k=top_k
    )
    
    # 4. Output & Persistence
    insight.save(result)
    logger.info(f"[{startup_slug}] Potential investors search complete. Results saved to {insight.path}")

    return [insight]
