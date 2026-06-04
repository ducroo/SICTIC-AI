import asyncio
import re
from typing import Dict, Tuple

from skills.dataset_chat.dataset_chat import dataset_chat
from skills.dataset_chat.dataset_chat import _fallback_trigger
from skills.config_load.config_load import config_load

from lib.insight_filepath import get_insight_filepath
from lib.model_config import llm_model
from lib.storage import get_storage
from lib.json_parser import repair_json_payload
from lib.logger import get_logger
from lib.insight_refresh import check_insight_refresh
from lib.slugify import slugify

logger = get_logger(__name__)


def _table_cell(value) -> str:
    return str(value).replace('|', '\\|').replace('\n', ' ')


class ChecklistParser:
    def __init__(self):
        self.idx = []
        self.header_level = 0

    def parse(self, item: str) -> Tuple[str, str, str, str]:
        """
        Returns (type, idx_string, display_text, query_text).
        type is either 'header' or 'question'.
        """
        clean_item = item.strip()
        is_header = clean_item.startswith('#')
        
        level = len(clean_item) - len(clean_item.lstrip('#')) if is_header else self.header_level + 1

        if is_header:
            self.header_level = level
            if is_header and level == 1:
                m = re.search(r'\d+', clean_item)
                self.idx = [int(m.group()) if m else 1]
            else:
                self.idx = (self.idx + [0] * level)[:level]
                self.idx[-1] += 1
        else:
            self.idx = (self.idx + [0] * level)[:level]
            self.idx[-1] += 1
            
        idx_string = '.'.join(map(str, self.idx))
        
        if is_header:
            title = clean_item.lstrip('#').strip()
            return "header", idx_string, title, clean_item
        else:
            # Clean display text: Remove leading bullets and trailing hints/keywords.
            line = re.sub(r'^[\*\-\+]\s+', '', clean_item)
            line = re.sub(r'^\d+\.\s+', '', line)
            display = re.split(r'(?i)(Keywords:|Hint:)', line)[0].strip()
            return "question", idx_string, display, clean_item

async def run_audit_query(dataset_name: str, query_text: str, idx_string: str, llm_instructions: str) -> Dict[str, str]:
    """Runs a single question against dataset_chat and robustly parses the JSON."""
    logger.info(f"[{dataset_name}] Auditing item {idx_string}: {query_text[:50]}...")
    try:
        raw_response = await dataset_chat(
            dataset_name,
            query_text,
            llm_instructions,
            strict_insufficient_context=False,
        )
        if raw_response and raw_response.strip() == _fallback_trigger():
            return {"status": "Not Found", "summary": "Not Found", "concerns": "None"}
    except Exception as e:
        logger.error(f"[{dataset_name}] LLM request failed for batch_audit item {idx_string}: {e}")
        return {"status": "Error", "summary": _table_cell(f"LLM request failed: {e}"), "concerns": "N/A"}

    try:
        json_result = repair_json_payload(raw_response if raw_response else "")
        status = str(json_result.get("status", "Error"))
        if status.strip() == _fallback_trigger():
            status = "Not Found"
        return {
            "status": _table_cell(status),
            "summary": _table_cell(json_result.get("summary", "Error")),
            "concerns": _table_cell(json_result.get("concerns", "Error"))
        }
    except Exception as e:
        logger.error(f"[{dataset_name}] Failed to parse batch_audit JSON response for {idx_string}: {e}")
        return {"status": "Error", "summary": _table_cell(f"Failed to parse LLM response: {e}"), "concerns": "N/A"}

async def batch_audit(dataset_name: str, checklist_string: str) -> str:
    """
    Concurrently processes a markdown checklist against a Qdrant dataset
    and returns a formatted Markdown table.
    """
    author = llm_model()
    parser = ChecklistParser()
    
    # 1. Find the first chapter title for filename generation
    chapter = None
    lines = checklist_string.strip().split('\n')
    for line in lines:
        if not line.strip():
            continue
        item_type, idx_string, display_text, query = parser.parse(line)
        if item_type == "header":
            chapter = display_text
            break
            
    if not chapter:
        raise ValueError("No chapter title found in the provided checklist.")
        
    dataset_slug = slugify(dataset_name)
    file_path = get_insight_filepath(
        dataset_name=dataset_slug,
        skill_name="batch_audit",
        model=author,
        identifier=chapter,
        subdir=True
    )

    needs_refresh, cached_content, matched_file = check_insight_refresh([dataset_slug], file_path)
    if not needs_refresh:
        if _fallback_trigger() in cached_content:
            logger.info(f"[{dataset_name}] Ignoring cached batch audit with fallback markers: {matched_file}")
        else:
            logger.info(f"[{dataset_name}] Using cached batch audit results from {matched_file}")
            return cached_content
    
    # Strict dictionary lookup
    config = config_load()
    table_lines = config["batch_audit"]["table_lines"]
    llm_instructions = config["batch_audit"]["llm_instructions"]

    # Phase A: Parse Checklist
    parser = ChecklistParser() # Reset parser after chapter search
    parsed_items = []
    
    for line in lines:
        if not line.strip():
            continue
            
        item_type, idx_string, display_text, query = parser.parse(line)
        
        if item_type == "header":
            parsed_items.append({
                "type": "header",
                "idx_string": idx_string,
                "title": display_text
            })
        else:
            parsed_items.append({
                "type": "question",
                "idx_string": idx_string,
                "display": display_text,
                "query": query
            })

    # Phase B: Execute Concurrently
    tasks = []
    for item in parsed_items:
        if item["type"] == "question":
            task = asyncio.create_task(run_audit_query(dataset_name, item["query"], item["idx_string"], llm_instructions))
            item["task"] = task
            tasks.append(task)
            
    if tasks:
        await asyncio.gather(*tasks)

    # Phase C: Assemble Markdown (Guarantees original order)
    for item in parsed_items:
        if item["type"] == "header":
            table_lines += f"\n| {item['idx_string']} | **{item['title']}** | | | | |"
        elif item["type"] == "question":
            result = item["task"].result()
            safe_display = item["display"].replace('|', '\\|').replace('\n', ' ')
            table_lines += f"\n| {item['idx_string']} | {safe_display} | {author} | {result['status']} | {result['summary']} | {result['concerns']} |"

    result_md = table_lines
    get_storage().write_text(file_path, result_md)

    return result_md
