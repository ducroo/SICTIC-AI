import json
from typing import Tuple, List, Optional
from skills.config_load.config_load import config_load
from skills.team_profile.core.discovery import discover_team
from skills.llm_chat.llm_chat import llm_chat
from skills.utils.env import get_env_var
from skills.utils.insight_refresh import check_insight_refresh
from skills.utils.ephemeral_dataset import prepare_ephemeral_dataset
from skills.utils.slugify import slugify
from skills.utils.storage import get_storage
from skills.utils.logger import get_logger

logger = get_logger(__name__)

async def team_profile(startup_name: str, files: Optional[List[str]] = None) -> Tuple[str, str]:
    """
    Performs deep-dive due diligence on a startup's leadership. Identifies founders, reconciles resumes with LinkedIn, and flags legal/background documents.
    """
    dataset_name = startup_name.lower()
    if files:
        dataset_name = "temp_team_profile"

    logger.info(f"[{dataset_name}] Starting Team Profiling")
    
    model_name = get_env_var("DEFAULT_LLM")
    clean_model_name = model_name.split("/")[-1]
    
    raw_filename_prefix = f"{startup_name.lower()}-team-profile"
    output_filename = f"{slugify(raw_filename_prefix)}-{slugify(clean_model_name)}.md"
    
    storage = get_storage()
    insights_dir = f"insights/{startup_name.lower()}"
    output_filepath = f"{insights_dir}/{output_filename}"

    needs_refresh, cached_content, matched_file = check_insight_refresh([startup_name], output_filepath, clean_model_name)
    if not needs_refresh:
        logger.info(f"[{dataset_name}] Using cached team profile from {matched_file}")
        return cached_content, matched_file
            
    config = config_load()
    
    # 1. Discovery (Web + Data Room)
    logger.info(f"[{dataset_name}] Executing Discovery phase...")
        
    linkedin_data, dataroom_context = await discover_team(dataset_name)
    
    # 2. Team Assessment Generation
    logger.info(f"[{dataset_name}] Generating final team profile report via LLM {model_name}...")
    
    assessment_prompt = config["team_profile"]["team_assessment_prompt"]
    assessment_prompt = assessment_prompt.replace("{{startupname}}", startup_name)
    
    classification_instructions = config["team_profile"]["linkedin_classification_prompt"]
     
    full_prompt = "### CONTEXT START ###\n\n"
    full_prompt += "#### LinkedIn Profiles (Source of Truth for dates/titles):\n"
    full_prompt += json.dumps(linkedin_data, indent=2)
    full_prompt += "\n\n#### Data Room Extracts (Resumes, Background Checks, etc.):\n"
    full_prompt += dataroom_context
    full_prompt += "\n### CONTEXT END ###\n\n"
    full_prompt += f"### INSTRUCTIONS ###\n\n"
    if classification_instructions:
        full_prompt += f"{classification_instructions}\n\n"
    full_prompt += f"{assessment_prompt}\n"
    
    try:
        report_md = await llm_chat(prompt=full_prompt)
        if not report_md:
            raise ValueError("LLM returned empty response.")
    except Exception as e:
        logger.error(f"[{dataset_name}] Failed to generate LLM report: {e}")
        raise RuntimeError(f"LLM Generation error: {e}")
    
    # 3. Output Generation
    storage.write_text(output_filepath, report_md)

    logger.info(f"[{dataset_name}] Team Profile saved to {output_filepath}")

    return report_md, output_filepath