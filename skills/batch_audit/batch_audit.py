import asyncio
import re
from typing import Dict, Tuple

from lib.insights import InsightFile
from lib.json_parser import repair_json_payload
from lib.logger import get_logger
from lib.model_config import llm_model
from lib.slugify import slugify
from skills.config_load.config_load import config_load
from skills.dataset_chat.dataset_chat import _fallback_trigger, dataset_chat

logger = get_logger(__name__)


def _table_cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _model_display_name(model: str) -> str:
    return model.rsplit("/", 1)[-1]


class ChecklistParser:
    def __init__(self):
        self.idx = []
        self.header_level = 0

    def parse(self, item: str) -> Tuple[str, str, str, str]:
        """Return item type, index, display text, and query text."""
        clean_item = item.strip()
        is_header = clean_item.startswith("#")
        level = (
            len(clean_item) - len(clean_item.lstrip("#"))
            if is_header
            else self.header_level + 1
        )

        if is_header:
            self.header_level = level
            if level == 1:
                match = re.search(r"\d+", clean_item)
                self.idx = [int(match.group()) if match else 1]
            else:
                self.idx = (self.idx + [0] * level)[:level]
                self.idx[-1] += 1
        else:
            self.idx = (self.idx + [0] * level)[:level]
            self.idx[-1] += 1

        idx_string = ".".join(map(str, self.idx))
        if is_header:
            return "header", idx_string, clean_item.lstrip("#").strip(), clean_item

        line = re.sub(r"^[\*\-\+]\s+", "", clean_item)
        line = re.sub(r"^\d+\.\s+", "", line)
        display = re.split(r"(?i)(Keywords:|Hint:)", line)[0].strip()
        return "question", idx_string, display, clean_item


async def run_audit_query(
    dataset_name: str,
    query_text: str,
    idx_string: str,
    llm_instructions: str,
) -> Dict[str, str]:
    """Run one checklist question and normalize its structured response."""
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
    except Exception as error:
        logger.error(
            f"[{dataset_name}] LLM request failed for batch_audit item "
            f"{idx_string}: {error}"
        )
        return {
            "status": "Error",
            "summary": _table_cell(f"LLM request failed: {error}"),
            "concerns": "N/A",
        }

    try:
        json_result = repair_json_payload(raw_response or "")
        status = str(json_result.get("status", "Error"))
        if status.strip() == _fallback_trigger():
            status = "Not Found"
        return {
            "status": _table_cell(status),
            "summary": _table_cell(json_result.get("summary", "Error")),
            "concerns": _table_cell(json_result.get("concerns", "Error")),
        }
    except Exception as error:
        logger.error(
            f"[{dataset_name}] Failed to parse batch_audit JSON response for "
            f"{idx_string}: {error}"
        )
        return {
            "status": "Error",
            "summary": _table_cell(f"Failed to parse LLM response: {error}"),
            "concerns": "N/A",
        }


async def batch_audit(dataset_name: str, checklist_string: str) -> str:
    """Process a Markdown checklist against a dataset and return a Markdown table."""
    model = llm_model()
    parser = ChecklistParser()
    lines = checklist_string.strip().splitlines()
    chapter = None

    for line in lines:
        if not line.strip():
            continue
        item_type, _idx, display_text, _query = parser.parse(line)
        if item_type == "header":
            chapter = display_text
            break

    if not chapter:
        raise ValueError("No chapter title found in the provided checklist.")

    dataset_slug = slugify(dataset_name)
    config = config_load()
    table_template = config["batch_audit"]["table_lines"]
    table_lines = f"**Model:** {_model_display_name(model)}\n\n{table_template}"
    llm_instructions = config["batch_audit"]["llm_instructions"]
    insight = InsightFile(
        dataset=dataset_slug,
        skill="batch_audit",
        model=model,
        identifier=chapter,
        subdir=True,
        prompt_key=checklist_string + llm_instructions + table_template,
    )

    reusable = insight.find_reusable()
    if reusable:
        cached_content = reusable.content()
        if _fallback_trigger() not in cached_content:
            logger.info(
                f"[{dataset_name}] Using cached batch audit results from {reusable.path}"
            )
            return cached_content
        logger.info(
            f"[{dataset_name}] Ignoring cached batch audit with fallback markers: "
            f"{reusable.path}"
        )

    parser = ChecklistParser()
    parsed_items = []
    for line in lines:
        if not line.strip():
            continue
        item_type, idx_string, display_text, query = parser.parse(line)
        if item_type == "header":
            parsed_items.append(
                {"type": "header", "idx_string": idx_string, "title": display_text}
            )
        else:
            parsed_items.append(
                {
                    "type": "question",
                    "idx_string": idx_string,
                    "display": display_text,
                    "query": query,
                }
            )

    tasks = []
    for item in parsed_items:
        if item["type"] == "question":
            task = asyncio.create_task(
                run_audit_query(
                    dataset_name,
                    item["query"],
                    item["idx_string"],
                    llm_instructions,
                )
            )
            item["task"] = task
            tasks.append(task)
    if tasks:
        await asyncio.gather(*tasks)

    for item in parsed_items:
        if item["type"] == "header":
            table_lines += (
                f"\n| {item['idx_string']} | **{item['title']}** | | | |"
            )
        else:
            result = item["task"].result()
            display = _table_cell(item["display"])
            table_lines += (
                f"\n| {item['idx_string']} | {display} | {result['status']} | "
                f"{result['summary']} | {result['concerns']} |"
            )

    insight.save(table_lines)
    return table_lines
