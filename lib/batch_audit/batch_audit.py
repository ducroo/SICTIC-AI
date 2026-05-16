import re
from typing import Dict

from lib.env import get_env_var
from lib.storage import get_storage
from skills.dataset_chat.dataset_chat import dataset_chat
from lib.json_parser import repair_json_payload
from lib.batch_audit.utils.outliner import DecimalOutliner
from skills.config_load.config_load import config_load
from lib.logger import get_logger
from lib.insight_refresh import check_insight_refresh
from lib.slugify import slugify

logger = get_logger(__name__)

def clean_line_item(line: str) -> str:
    """Removes leading bullets and trailing hints/keywords."""
    line = re.sub(r'^[\*\-\+]\s+', '', line.strip())
    line = re.sub(r'^\d+\.\s+', '', line)
    line = re.split(r'(?i)(Keywords:|Hint:)', line)[0]
    return line.strip()

async def batch_audit(dataset_name: str, checklist_string: str) -> str:
    """
    Sequentially processes a markdown checklist against a Qdrant dataset
    and returns a formatted Markdown table.
    """
    author = get_env_var("DEFAULT_LLM")
    model_suffix = author.split("/")[-1]
    outliner = DecimalOutliner()
    
    # 1. Find the first chapter title
    chapter = None
    lines = checklist_string.strip().split('\n')
    for line in lines:
        if not line.strip():
            continue
        is_header, title_text, _ = outliner.parse(line)
        if is_header:
            chapter = title_text
            break
            
    if not chapter:
        raise ValueError("No chapter title found in the provided checklist.")
        
    raw_filename_prefix = f"batch-audit/{slugify(chapter)}"
    file_name = f"{slugify(raw_filename_prefix)}-{slugify(model_suffix)}.md"
    file_path = f"insights/{dataset_name.lower()}/{file_name}"

    needs_refresh, cached_content, matched_file = check_insight_refresh([dataset_name], file_path, model_suffix)
    if not needs_refresh:
        logger.info(f"[{dataset_name}] Using cached batch audit results from {matched_file}")
        return cached_content
    
    batch_audit_config = config_load().get("batch_audit", {})

    table_lines = batch_audit_config.get("table_lines", "")
    llm_instructions = batch_audit_config.get("llm_instructions", "")

    lines = checklist_string.strip().split('\n')
    for line in lines:
        if not line.strip():
            continue
            
        is_header, title_text, idx_string = outliner.parse(line)
        
        if is_header:
            table_lines += f"\n| {idx_string} | **{title_text}** | | | | |"
        else:
            display_text = clean_line_item(line)
            query_text = line.strip()
            
            logger.info(f"[{dataset_name}] Auditing item {idx_string}: {display_text}")
            
            raw_response = await dataset_chat(dataset_name, query_text, llm_instructions)
            
            try:
                json_result = repair_json_payload(raw_response if raw_response else "")
            except Exception as e:
                logger.error(f"[{dataset_name}] Failed to parse batch_audit JSON response for {idx_string}: {e}")
                json_result = {"status": "Error", "summary": "Failed to parse LLM response.", "concerns": "N/A"}
            
            status = str(json_result.get("status", "Error")).replace('|', '\\|').replace('\n', ' ')
            summary = str(json_result.get("summary", "Error")).replace('|', '\\|').replace('\n', ' ')
            concerns = str(json_result.get("concerns", "Error")).replace('|', '\\|').replace('\n', ' ')
            safe_display = display_text.replace('|', '\\|').replace('\n', ' ')
            
            table_lines += f"\n| {idx_string} | {safe_display} | {author} | {status} | {summary} | {concerns} |"

    result_md = table_lines
    get_storage().write_text(file_path, result_md)

    return result_md
