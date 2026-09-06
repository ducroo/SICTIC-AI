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

async def potential_investors(startup_name: str, target_investors: Optional[List[str]] = None, exclude_investors: Optional[List[str]] = None, top_k: int = 16) -> InsightResult:
    """
    Rank stored investor profiles for their fit with a startup.
    """
    startup_slug = slugify(startup_name)
    from lib.startups.sources import ensure_startup_dataset

    status = await ensure_startup_dataset(startup_slug)
    startup_slug = status.dataset_slug
    startup_name = startup_slug
    default_llm = llm_model()

    try:
        config = load_repository_config()
        objective_template = config['potential_investors']['objective']
    except Exception as e:
        logger.error(f"[{startup_slug}] Failed to load configuration: {e}")
        raise RuntimeError(f"Failed to load configuration: {e}")
    insight = InsightFile(
        dataset=startup_slug,
        skill="potential_investors",
        model=default_llm,
        source_datasets=[startup_slug, "sictic-members"],
        config_key=config_cache_key(
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
    stored = insight.find(selection="any")
    if stored is not None and stored.model == "manual":
        return [stored]
    # 1. Fetch Startup Profile
    logger.info(f"[{startup_slug}] Fetching startup profile...")
    try:
        [profile_insight] = await startup_profile(startup_name)
        profile_content = profile_insight.content()
    except Exception as e:
        logger.error(f"[{startup_slug}] Failed to generate/fetch startup profile: {e}")
        raise RuntimeError(f"Failed to generate/fetch startup profile: {e}")

    # Indexed dataset revisions do not track edits to profile insights.
    insight.config_key = config_cache_key(
        insight.config_key, {"startup_profile": profile_content}
    )
    if reusable := insight.find(selection="reusable"):
        return [reusable]

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
