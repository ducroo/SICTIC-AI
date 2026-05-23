from typing import Optional
from lib.env import get_env_var
from lib.storage import get_storage
from lib.logger import get_logger
from lib.insight_filepath import get_insight_filepath
from lib.insight_refresh import check_insight_refresh
from skills.config_load.config_load import config_load
from skills.dataset_chat.dataset_chat import dataset_chat

logger = get_logger(__name__)

async def generate_dataset_insight(
    dataset_name: str,
    skill_name: str,
    config_key: str,
    max_chunks: int = 25,
    return_full_docs: bool = False
) -> str:
    """
    Generic pipeline to generate an insight by chatting with a dataset.
    Handles cache checking, config loading, executing dataset_chat, and saving output.
    """
    dataset_name_lower = dataset_name.lower()
    default_llm = get_env_var("DEFAULT_LLM")
    storage = get_storage()
    
    output_path = get_insight_filepath(
        dataset_name=dataset_name_lower,
        skill_name=skill_name,
        model=default_llm,
        subdir=False
    )

    needs_refresh, cached_content, matched_file = check_insight_refresh([dataset_name_lower], output_path, default_llm)
    if not needs_refresh:
        logger.info(f"[{dataset_name_lower}] Using cached {skill_name} from {matched_file}")
        return cached_content

    logger.info(f"[{dataset_name_lower}] Generating new {skill_name}...")

    try:
        conf = config_load()
        if config_key not in conf:
            raise KeyError(f"{config_key} config missing")
        query = conf[config_key]['query']
        llm_instructions = conf[config_key]['llm_instructions']
    except KeyError as e:
        logger.error(f"[{dataset_name_lower}] Missing configuration: {e}")
        raise ValueError(f"Missing configuration for {skill_name}: {e}")

    raw_response = await dataset_chat(
        dataset_name=dataset_name_lower,
        questions=query,
        llm_instructions=llm_instructions,
        max_chunks=max_chunks,
        return_full_docs=return_full_docs
    )

    result_md = raw_response if raw_response else "No relevant information found."
    storage.write_text(output_path, result_md)
    logger.info(f"[{dataset_name_lower}] Successfully saved {skill_name} to {output_path}")

    return result_md