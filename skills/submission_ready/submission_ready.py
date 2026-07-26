import asyncio
from typing import Any

from lib.datasets.ingestion import sync_datasets
from lib.datasets.paths import dataset_raw_path
from lib.insights import InsightFile
from lib.json_parser import repair_json_payload
from lib.logger import get_logger
from lib.model_config import llm_model
from lib.slugify import slugify
from lib.storage import get_storage
from skills.batch_audit.batch_audit import ChecklistParser
from skills.config_load.config_load import config_load
from skills.dataset_chat.dataset_chat import _fallback_trigger, dataset_chat

logger = get_logger(__name__)

VALID_JUDGMENTS = {"Pass", "Fail", "Unclear"}


def _table_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _source_documents(value: Any) -> str:
    if isinstance(value, list):
        sources = [str(item).strip() for item in value if str(item).strip()]
        return "; ".join(sources) if sources else "None"
    rendered = str(value or "").strip()
    return rendered or "None"


def _unclear_result(assessment: str, next_step: str) -> dict[str, str]:
    return {
        "judgment": "Unclear",
        "assessment": _table_cell(assessment),
        "source_documents": "None",
        "proposed_next_step": _table_cell(next_step),
    }


async def run_submission_query(
    dataset_name: str,
    query_text: str,
    idx_string: str,
    llm_instructions: str,
) -> dict[str, str]:
    """Evaluate one screening item and normalize its strict JSON response."""
    logger.info(
        "[%s] Checking submission item %s: %s...",
        dataset_name,
        idx_string,
        query_text[:80],
    )
    try:
        raw_response = await dataset_chat(
            dataset_name,
            query_text,
            llm_instructions,
            strict_insufficient_context=False,
        )
    except Exception as error:
        logger.error(
            "[%s] LLM request failed for submission item %s: %s",
            dataset_name,
            idx_string,
            error,
        )
        return _unclear_result(
            f"Automated check failed: {error}",
            "Retry this check before making an Ops decision.",
        )

    if not raw_response or raw_response.strip() == _fallback_trigger():
        return _unclear_result(
            "The submitted Dealum evidence does not establish this item.",
            "Move to Under Review and request the missing or clarifying evidence.",
        )

    try:
        result = repair_json_payload(raw_response)
    except Exception as error:
        logger.error(
            "[%s] Failed to parse submission JSON for item %s: %s",
            dataset_name,
            idx_string,
            error,
        )
        return _unclear_result(
            f"Automated response could not be parsed: {error}",
            "Retry this check before making an Ops decision.",
        )
    if not isinstance(result, dict):
        return _unclear_result(
            "The automated response was not a JSON object.",
            "Retry this check before making an Ops decision.",
        )

    judgment = str(result.get("judgment", "")).strip().title()
    if judgment not in VALID_JUDGMENTS:
        return _unclear_result(
            f"The automated response returned an invalid judgment: {judgment or 'empty'}.",
            "Retry this check before making an Ops decision.",
        )

    return {
        "judgment": _table_cell(judgment),
        "assessment": _table_cell(
            result.get("assessment", "No written assessment was returned.")
        ),
        "source_documents": _table_cell(
            _source_documents(result.get("source_documents"))
        ),
        "proposed_next_step": _table_cell(
            result.get("proposed_next_step", "Review manually.")
        ),
    }


async def _run_checklist(
    dataset_name: str,
    checklist: str,
    llm_instructions: str,
    table_lines: str,
) -> str:
    parser = ChecklistParser()
    parsed_items: list[dict[str, Any]] = []
    for line in checklist.strip().splitlines():
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

    if not any(item["type"] == "header" for item in parsed_items):
        raise ValueError("No checklist chapter title found.")

    tasks = []
    for item in parsed_items:
        if item["type"] != "question":
            continue
        task = asyncio.create_task(
            run_submission_query(
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
                f"\n| {item['idx_string']} | **{_table_cell(item['title'])}** "
                "| | | | |"
            )
            continue
        result = item["task"].result()
        table_lines += (
            f"\n| {item['idx_string']} | {_table_cell(item['display'])} | "
            f"{result['judgment']} | {result['assessment']} | "
            f"{result['source_documents']} | {result['proposed_next_step']} |"
        )
    return table_lines


async def submission_ready(dataset_name: str) -> str:
    """Check a Dealum submission for completeness and initial eligibility."""
    startup_slug = slugify(dataset_name)
    from lib.startups.sources import ensure_startup_dataset

    status = await ensure_startup_dataset(startup_slug)
    startup_slug = status.dataset_slug
    storage = get_storage()
    raw_path = dataset_raw_path(startup_slug)
    if not storage.exists(raw_path):
        raise ValueError(f"Dataset for {startup_slug} not found at {raw_path}.")
    await sync_datasets([startup_slug], raise_on_error=True)

    config = config_load()
    check_config = config["submission_ready"]
    policy = check_config["policy"]
    checklist = check_config["checklist"]
    llm_instructions = f"{policy}\n\n{check_config['llm_instructions']}"
    table_lines = check_config["table_lines"]
    prompt_key = "\n\n".join(
        [policy, checklist, check_config["llm_instructions"], table_lines]
    )
    insight = InsightFile(
        dataset=startup_slug,
        skill="submission_ready",
        model=llm_model(),
        prompt_key=prompt_key,
    )
    reusable = insight.find_reusable()
    if reusable:
        logger.info(
            "[%s] Using cached submission readiness check from %s",
            startup_slug,
            reusable.path,
        )
        return reusable.path

    table = await _run_checklist(
        startup_slug,
        checklist,
        llm_instructions,
        table_lines,
    )
    report = (
        f"# Completeness and Eligibility Check for {dataset_name}\n\n"
        "Scope: Dealum submission completeness and SICTIC initial eligibility. "
        "This is not a pitch-readiness or investment-quality assessment.\n\n"
        f"{table}\n"
    )
    insight.save(report)
    return insight.path
