from typing import Tuple
from skills.config_load.config_load import config_load
from skills.person_profile.person_profile import person_profile
from skills.llm_chat.llm_chat import llm_chat
from lib.datasets.search import dataset_search
from lib.model_config import llm_model
from lib.insights import InsightFile
from lib.datasets.ingestion import sync_datasets
from lib.slugify import slugify
from lib.logger import get_logger

logger = get_logger(__name__)

async def team_profile(startup_name: str) -> Tuple[str, str]:
    """
    Performs deep-dive due diligence on a startup's leadership. Identifies founders,
    synthesizes person profiles, and evaluates the team composition.
    """
    dataset_name = slugify(startup_name)
    from lib.startups.sources import ensure_startup_dataset

    status = await ensure_startup_dataset(dataset_name)
    dataset_name = status.dataset_slug
    await sync_datasets([dataset_name], raise_on_error=True)

    logger.info(f"[{dataset_name}] Starting Team Profiling")

    default_llm = llm_model()
    config = config_load()
    resume_queries = config["team_profile"]["resume_queries"]
    assessment_prompt = config["team_profile"]["team_assessment_prompt"]
    assessment_prompt = assessment_prompt.replace("{{startupname}}", startup_name)
    classification_instructions = config.get("team_profile", {}).get(
        "linkedin_classification_prompt",
        "",
    )
    prompt_key = str(resume_queries) + assessment_prompt + classification_instructions
    insight = InsightFile(
        dataset=dataset_name,
        skill="team_profile",
        model=default_llm,
        prompt_key=prompt_key,
    )
    reusable = insight.find_reusable()
    if reusable:
        logger.info(f"[{dataset_name}] Using cached team profile from {reusable.path}")
        return reusable.content(), reusable.path
    
    # 1. Discovery (via person_profile)
    logger.info(f"[{dataset_name}] Fetching person profiles for the team...")
    persons = await person_profile(startup_name, names=None)
    
    if not persons:
        logger.warning(f"[{dataset_name}] No persons discovered. Proceeding with empty context.")
        
    # 1.5 Resume / CV Semantic Search
    resume_chunks = []
    if resume_queries:
        logger.info(f"[{dataset_name}] Fetching collective set of resume/CV chunks via semantic search...")
        try:
            resume_chunks = await dataset_search(dataset_name=dataset_name, query=resume_queries)
        except Exception as e:
            logger.error(f"[{dataset_name}] Collective resume semantic search failed: {e}")

    # 2. Team Assessment Generation
    logger.info(f"[{dataset_name}] Generating final team profile report via LLM {default_llm}...")
    
    full_prompt = "### CONTEXT START ###\n\n"
    
    # Extract and deduplicate all mentions across the entire team and resume chunks
    unique_mentions = {}
    for p in persons:
        if p.mentions:
            for m in p.mentions:
                unique_mentions[m.chunk_id] = m
                
    for chunk in resume_chunks:
        unique_mentions[chunk.chunk_id] = chunk
                
    if unique_mentions:
        full_prompt += "#### AGGREGATED TEAM DATA ROOM MENTIONS ####\n\n"
        for chunk in unique_mentions.values():
            full_prompt += f"{chunk.to_md()}\n\n"
            
    full_prompt += "#### DISCOVERED PERSONS (Synthesized Profiles) ####\n\n"
    for p in persons:
        full_prompt += f"**Name:** {p.full_name}\n"
        full_prompt += f"**LinkedIn ID:** {p.linkedin_id}\n\n"
        if p.person_profile:
            full_prompt += f"**Profile Summary:**\n{p.person_profile}\n\n"
        full_prompt += "---\n\n"
        
    full_prompt += "### CONTEXT END ###\n\n"
    full_prompt += "### INSTRUCTIONS ###\n\n"
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
    insight.save(report_md)
    logger.info(f"[{dataset_name}] Team Profile saved to {insight.path}")

    return report_md, insight.path
