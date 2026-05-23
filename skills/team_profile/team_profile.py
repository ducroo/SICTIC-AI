import json
from typing import Tuple, List, Optional
from skills.config_load.config_load import config_load
from skills.team_profile.core.discovery import discover_team
from skills.llm_chat.llm_chat import llm_chat
from lib.env import get_env_var
from lib.storage import get_storage
from lib.insight_refresh import check_insight_refresh
from lib.ephemeral_dataset import prepare_ephemeral_dataset
from lib.slugify import slugify
from lib.logger import get_logger

logger = get_logger(__name__)

async def team_profile(startup_name: str, files: Optional[List[str]] = None) -> Tuple[str, str]:
    """
    Performs deep-dive due diligence on a startup's leadership. Identifies founders, reconciles resumes with LinkedIn, and flags legal/background documents.
    """
    dataset_name = startup_name.lower()
    if files:
        dataset_name = "temp_team_profile"

    logger.info(f"[{dataset_name}] Starting Team Profiling")

    storage = get_storage()
    default_llm = get_env_var("DEFAULT_LLM")
    
    from lib.insight_filepath import get_insight_filepath
    output_filepath = get_insight_filepath(
        dataset_name=startup_name.lower(),
        skill_name="team_profile",
        model=default_llm,
        subdir=False
    )
    
    needs_refresh, cached_content, matched_file = check_insight_refresh([startup_name], output_filepath, default_llm)
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