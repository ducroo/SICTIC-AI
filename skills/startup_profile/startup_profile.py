import os
from typing import List, Optional, Tuple


from skills.utils.env import get_env_var
from skills.config_load.config_load import config_load
from skills.llm_chat.llm_chat import llm_chat
from skills.dataset_chat.dataset_chat import dataset_chat
from skills.utils.adapters.qdrant import QdrantAdapter
from skills.utils.ephemeral_dataset import prepare_ephemeral_dataset
from skills.utils.insight_refresh import check_insight_refresh
from skills.utils.slugify import slugify
from skills.utils.logger import get_logger

logger = get_logger(__name__)


async def startup_profile(startup: str, files: Optional[List[str]] = None) -> Tuple[str, str]:
    """
    Generates a neutral, objective 5-point diagnostic of a startup. It bypasses marketing narratives to expose the structural reality of the business, prioritizing external risks and identifying specific tasks for an investment analyst. Use this skill when the user asks "Profile this startup", "Run startup diagnostic", or "What does this startup do?". Note that if no context/document is provided via the GUI, the <STARTUP_NAME> must be clearly specified in the query.
    """
    startup_name_lower = startup.lower()
    gdrive_mount = get_env_var("GDRIVE_MOUNT")
    default_llm = get_env_var("DEFAULT_LLM")
    
    safe_llm_name = default_llm.split('/')[-1]
    
    raw_filename_prefix = f"{startup_name_lower}-startup-profile"
    output_filename = f"{slugify(raw_filename_prefix)}-{slugify(safe_llm_name)}.md"
    output_dir = os.path.join(gdrive_mount, "insights", startup_name_lower)
    output_file = os.path.join(output_dir, output_filename)
    
    needs_refresh, cached_content, matched_file = check_insight_refresh([startup_name_lower], output_file, safe_llm_name)
    if not needs_refresh:
        return cached_content, matched_file

    config = config_load()
    if 'startup_profile' not in config:
        raise KeyError("startup_profile config missing")
    query = config['startup_profile']['query']
    llm_instructions = config['startup_profile']['llm_instructions']

    context_block = ""
    profile_output = ""

    dataset_name = startup_name_lower
    if files:
        dataset_name = prepare_ephemeral_dataset(files, temp_name="temp_startup_profile")
        
    profile_output = await dataset_chat(dataset_name=dataset_name, questions=query, llm_instructions=llm_instructions)

    if profile_output is None:
        raise ValueError("LLM returned None for the profile output.")
        
    os.makedirs(output_dir, exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(profile_output)

    return profile_output, output_file
