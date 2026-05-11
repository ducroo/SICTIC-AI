import os
from skills.utils.env import get_env_var
from skills.config_load.config_load import config_load
from skills.batch_audit.batch_audit import batch_audit
from skills.dataset_chat.dataset_chat import dataset_chat
from skills.utils.adapters.qdrant import QdrantAdapter
from skills.utils.slugify import slugify
from skills.utils.logger import get_logger

logger = get_logger(__name__)



def initialize_report_file(startup_name_lower: str, startup: str) -> str:
    gdrive_mount = get_env_var("GDRIVE_MOUNT")
    default_llm = get_env_var("DEFAULT_LLM")
    safe_llm_name = default_llm.split('/')[-1]
    
    output_dir = os.path.join(gdrive_mount, "insights", startup_name_lower)
    os.makedirs(output_dir, exist_ok=True)
    
    raw_filename = f"{startup_name_lower}-dd-checks-{safe_llm_name}"
    output_file = os.path.join(output_dir, f"{slugify(raw_filename)}.md")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"# M&A Due Diligence Checks for {startup}\n\n")
    return output_file

async def find_industry_type(startup_name_lower: str, dd_config: dict, allowed_industry_types: set) -> str:
    industry_prompt = dd_config['industry_type_query']
    industry_instructions = dd_config['industry_type_llm_instructions']
    industry_response = await dataset_chat(dataset_name=startup_name_lower, questions=industry_prompt, llm_instructions=industry_instructions, max_chunks=5)
    
    logger.info(f"[{startup_name_lower}] Raw Industry Type LLM Response: {industry_response}")
    response_lower = industry_response.lower()
    for allowed in allowed_industry_types:
        if allowed.lower() in response_lower:
            return allowed
            
    return "general"

async def chapter_by_chapter(startup_name_lower: str, sorted_chapters: list, industry_type: str, dd_config: dict, output_file: str):
    checklists = dd_config['checklists']
    for chapter in sorted_chapters:
        target_key = f"{chapter}_{industry_type}"
        fallback_key = f"{chapter}_general"
        checklist_key = target_key if target_key in checklists else (fallback_key if fallback_key in checklists else None)
        if not checklist_key:
            continue
            
        checklist_string = checklists[checklist_key]
        try:
            chapter_output = await batch_audit(dataset_name=startup_name_lower, checklist_string=checklist_string)
            with open(output_file, 'a', encoding='utf-8') as f:
                f.write(f"## Chapter: {chapter}\n\n{chapter_output}\n\n")
        except Exception as e:
            with open(output_file, 'a', encoding='utf-8') as f:
                f.write(f"## Chapter: {chapter}\n\n**Error:** Failed to process chapter due to: {e}\n\n")

async def dd_checks(startup: str) -> str:
    """
    Performs a comprehensive M&A-style due diligence review of a startup's data room using predefined, industry-aware checklists. It automatically identifies the startup's industry, selects the appropriate checklists, searches the data room, and generates a single, complete Markdown report file in the background.
    """
    startup_name_lower = startup.lower()
    qdrant = QdrantAdapter(collection_name=startup_name_lower)
    if not qdrant.dataset_available():
        raise ValueError(f"Dataset for {startup_name_lower} not found or is empty.")
        
    output_file = initialize_report_file(startup_name_lower, startup)
    config = config_load()
    dd_config = config['dd_checks']
    checklists = dd_config['checklists']

    chapters, allowed_industry_types = set(), set()
    for key in checklists.keys():
        parts = key.rsplit('_', 1)
        if len(parts) == 2:
            chapters.add(parts[0])
            allowed_industry_types.add(parts[1])

    sorted_chapters = sorted(list(chapters))
    if not sorted_chapters:
        raise ValueError("No valid chapters found in the configuration.")

    industry_type = await find_industry_type(startup_name_lower, dd_config, allowed_industry_types)
    await chapter_by_chapter(startup_name_lower, sorted_chapters, industry_type, dd_config, output_file)
    return output_file
