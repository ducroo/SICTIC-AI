from typing import List, Optional, Tuple


from lib.env import get_env_var
from lib.storage import get_storage
from skills.config_load.config_load import config_load
from skills.llm_chat.llm_chat import llm_chat
from skills.dataset_chat.dataset_chat import dataset_chat
from lib.adapters.qdrant import QdrantAdapter
from lib.ephemeral_dataset import prepare_ephemeral_dataset
from lib.insight_refresh import check_insight_refresh
from lib.slugify import slugify
from lib.logger import get_logger

logger = get_logger(__name__)

_INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"


async def startup_profile(startup: str, files: Optional[List[str]] = None) -> Tuple[str, str]:
    """
    Generates a neutral, objective 5-point diagnostic of a startup. It bypasses marketing narratives to expose the structural reality of the business, prioritizing external risks and identifying specific tasks for an investment analyst. Use this skill when the user asks "Profile this startup", "Run startup diagnostic", or "What does this startup do?". Note that if no context/document is provided via the GUI, the <STARTUP_NAME> must be clearly specified in the query.
    """
    startup_slug = slugify(startup)
    storage = get_storage()
    default_llm = get_env_var("DEFAULT_LLM")
    
    from lib.insight_filepath import get_insight_filepath
    output_file = get_insight_filepath(
        dataset_name=startup_slug,
        skill_name="startup_profile",
        model=default_llm,
        subdir=False
    )

    needs_refresh, cached_content, matched_file = check_insight_refresh([startup_slug], output_file, default_llm)
    if not needs_refresh:
        return cached_content, matched_file

    config = config_load()
    if 'startup_profile' not in config:
        raise KeyError("startup_profile config missing")
    query = config['startup_profile']['query']
    llm_instructions = config['startup_profile']['llm_instructions']

    dataset_name = startup_slug
    if files:
        dataset_name = await prepare_ephemeral_dataset(files, temp_name="temp_startup_profile")

    profile_output = await dataset_chat(dataset_name=dataset_name, questions=query, llm_instructions=llm_instructions)

    if profile_output is None:
        raise ValueError("LLM returned None for the profile output.")
    if _INSUFFICIENT_CONTEXT in profile_output.strip():
        raise ValueError(
            f"Insufficient indexed context for startup '{startup_slug}'. "
            "Check dataset sync, parsed markdown, and Qdrant ingestion before generating a profile."
        )

    storage.write_text(output_file, profile_output)
    return profile_output, output_file
