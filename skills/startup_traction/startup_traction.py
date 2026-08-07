from lib.datasets.ingestion import sync_datasets
from lib.insights import InsightFile, InsightResult
from lib.logger import get_logger
from lib.model_config import llm_model
from lib.slugify import slugify
from skills.config_load.config_load import config_load
from skills.dataset_chat.dataset_chat import _fallback_trigger, dataset_chat

logger = get_logger(__name__)

async def startup_traction(startup_name: str) -> InsightResult:
    """
    Extracts, analyzes, and summarizes all commercial traction and agreements (LoIs, MoUs, Pilot agreements) from a startup's data room into a structured overview table and synthesis.
    """
    dataset_slug = slugify(startup_name)
    from lib.startups.sources import ensure_startup_dataset

    status = await ensure_startup_dataset(dataset_slug)
    dataset_slug = status.dataset_slug
    await sync_datasets([dataset_slug], raise_on_error=True)

    config = config_load()
    try:
        query = config["startup_traction"]["query"]
        llm_instructions = config["startup_traction"]["llm_instructions"]
    except KeyError as error:
        raise ValueError(f"Missing configuration for startup_traction: {error}") from error

    insight = InsightFile(
        dataset=dataset_slug,
        skill="startup_traction",
        model=llm_model(),
        prompt_key=query + llm_instructions,
    )
    reusable = insight.find_reusable()
    if reusable:
        logger.info(f"[{dataset_slug}] Using cached startup_traction from {reusable.path}")
        return [reusable]

    result = await dataset_chat(
        dataset_name=dataset_slug,
        queries=query,
        prompt=f"Query: {query}\n\nInstructions: {llm_instructions}",
        max_chunks=100,
        strict_insufficient_context=False,
    )
    result = result or "No relevant information found."
    if result.strip() == _fallback_trigger():
        raise ValueError(
            f"Insufficient indexed context for startup_traction on dataset '{dataset_slug}'. "
            "No insight was saved."
        )

    insight.save(result)
    logger.info(f"[{dataset_slug}] Successfully saved startup_traction to {insight.path}")
    return [insight]
