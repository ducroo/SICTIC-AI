from typing import List, Optional


from lib.model_config import llm_model
from skills.config_load.config_load import config_load
from skills.dataset_chat.dataset_chat import dataset_chat
from lib.ephemeral_dataset import prepare_ephemeral_dataset
from lib.insights import InsightFile, InsightResult
from lib.slugify import slugify
from lib.logger import get_logger
from lib.datasets.ingestion import sync_datasets

logger = get_logger(__name__)


async def startup_profile(startup: str, files: Optional[List[str]] = None) -> InsightResult:
    """
    Generates a neutral, objective 5-point diagnostic of a startup. It bypasses marketing narratives to expose the structural reality of the business, prioritizing external risks and identifying specific tasks for an investment analyst. Use this skill when the user asks "Profile this startup", "Run startup diagnostic", or "What does this startup do?". Note that if no context/document is provided via the GUI, the <STARTUP_NAME> must be clearly specified in the query.
    """
    startup_slug = slugify(startup)
    from lib.startups.sources import ensure_startup_dataset

    status = await ensure_startup_dataset(startup_slug)
    startup_slug = status.dataset_slug
    await sync_datasets([startup_slug], raise_on_error=True)
    default_llm = llm_model()

    config = config_load()
    if 'startup_profile' not in config:
        raise KeyError("startup_profile config missing")
    query = config['startup_profile']['query']
    llm_instructions = config['startup_profile']['llm_instructions']
    questions = [line.strip() for line in query.splitlines() if line.strip()]

    insight = InsightFile(
        dataset=startup_slug,
        skill="startup_profile",
        model=default_llm,
        config_key=query + llm_instructions,
    )
    if not files:
        reusable = insight.find(selection="reusable")
        if reusable:
            return [reusable]

    dataset_name = startup_slug
    if files:
        dataset_name = await prepare_ephemeral_dataset(files, temp_name="temp_startup_profile")

    profile_output = await dataset_chat(
        dataset_name=dataset_name,
        queries=questions,
        prompt=(
            f"Query: {'\n\n'.join(questions)}\n\n"
            f"Instructions: {llm_instructions}"
        ),
    )

    if profile_output is None:
        raise ValueError("LLM returned None for the profile output.")
    insight.save(profile_output)
    return [insight]
