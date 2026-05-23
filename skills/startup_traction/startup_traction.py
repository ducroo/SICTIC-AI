from lib.env import get_env_var
from lib.storage import get_storage
from lib.logger import get_logger
from lib.insight_refresh import check_insight_refresh
from skills.config_load.config_load import config_load
from skills.dataset_chat.dataset_chat import dataset_chat
from lib.slugify import slugify

logger = get_logger(__name__)

async def startup_traction(startup_name: str) -> str:
    """
    Extracts, analyzes, and summarizes all commercial traction and agreements (LoIs, MoUs, Pilot agreements) from a startup's data room into a structured overview table and synthesis.
    """
    startup_name_lower = startup_name.lower()
    storage = get_storage(get_env_var("REPOSITORY_DIR"))
    model_suffix = get_env_var("DEFAULT_LLM").split('/')[-1]

    raw_filename_prefix = f"{startup_name_lower}-startup-traction"
    file_name = f"{slugify(raw_filename_prefix)}-{slugify(model_suffix)}.md"
    output_path = f"insights/{startup_name_lower}/{file_name}"

    needs_refresh, cached_content, matched_file = check_insight_refresh([startup_name_lower], output_path, model_suffix)
    if not needs_refresh:
        logger.info(f"[{startup_name_lower}] Using cached startup_traction from {matched_file}")
        return cached_content

    logger.info(f"[{startup_name_lower}] Generating new startup_traction...")

    try:
        conf = config_load()
        query = conf['startup_traction']['query']
        llm_instructions = conf['startup_traction']['llm_instructions']
    except KeyError as e:
        logger.error(f"[{startup_name_lower}] Missing configuration: {e}")
        raise ValueError(f"Missing configuration for startup_traction: {e}")

    raw_response = await dataset_chat(
        dataset_name=startup_name_lower,
        questions=query,
        llm_instructions=llm_instructions,
        return_full_docs=False,
        max_chunks=100
    )

    result_md = raw_response if raw_response else "No relevant information found."
    storage.write_text(output_path, result_md)
    logger.info(f"[{startup_name_lower}] Successfully saved startup_traction to {output_path}")

    return result_md
