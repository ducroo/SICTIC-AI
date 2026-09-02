import asyncio
import json
from functools import partial
from typing import Any

from lib.batch_audit import batch_audit
from lib.batch_audit.rendering import json_to_markdown_table
from lib.batch_audit.schema import audit_errors, validate_audit_document
from lib.datasets.ingestion import sync_datasets
from lib.datasets.paths import dataset_raw_path
from lib.insights import InsightFile, InsightResult
from lib.infrastructure.ai_text_generation import Review
from lib.infrastructure.ai_text_generation.json import (
    copy_schema,
    repair_json_payload,
    validate_json_schema,
)
from lib.infrastructure.configuration import (
    config_cache_key,
    load_repository_config,
)
from lib.infrastructure.logging import get_logger
from lib.model_config import llm_model
from lib.slugify import slugify
from lib.storage import get_storage
from skills.dataset_chat.dataset_chat import dataset_chat_json

logger = get_logger(__name__)


def _industry_response_schema(
    response_schema: dict[str, Any],
    allowed_industry_types: set[str],
) -> dict[str, Any]:
    specialized = copy_schema(response_schema)
    allowed = sorted(allowed_industry_types)
    try:
        specialized["properties"]["industry_type"]["enum"] = [
            *allowed,
            None,
        ]
    except (KeyError, TypeError) as error:
        raise ValueError(
            "dd_checks.industry_type_response_schema must define "
            "properties.industry_type."
        ) from error
    return specialized


def parse_industry_type(
    response: str,
    allowed_industry_types: set[str],
    response_schema: dict[str, Any],
) -> str:
    """Repair and validate a structured industry classification."""
    effective_schema = _industry_response_schema(
        response_schema,
        allowed_industry_types,
    )
    result = repair_json_payload(response)
    validate_json_schema(
        result,
        effective_schema,
        label="DD industry-classification response",
    )
    return _industry_type_from_result(result, allowed_industry_types)


def _industry_type_from_result(
    result: dict[str, Any],
    allowed_industry_types: set[str],
) -> str:
    allowed_by_lower = {
        item.lower(): item for item in allowed_industry_types
    }
    industry_type = result["industry_type"]
    if industry_type is None:
        logger.warning(
            "Industry classification had insufficient evidence; "
            "defaulting to general."
        )
        return allowed_by_lower.get("general", "general")
    evidence = [item.strip() for item in result["evidence"] if item.strip()]
    if not evidence:
        raise ValueError(
            "Industry classification requires evidence when a type is selected."
        )
    return allowed_by_lower[industry_type.lower()]


def _review_industry_type(
    output: dict | list,
    allowed_industry_types: set[str],
) -> Review[dict | list]:
    if not isinstance(output, dict):
        return Review(output, ("Industry classification must be an object",))
    try:
        _industry_type_from_result(output, allowed_industry_types)
    except (KeyError, TypeError, ValueError) as error:
        return Review(output, (str(error),))
    return Review(output)


async def find_industry_type(
    startup_name_lower: str,
    dd_config: dict,
    allowed_industry_types: set,
) -> str:
    industry_prompt = dd_config['industry_type_query']
    industry_instructions = dd_config['industry_type_llm_instructions']
    base_schema = dd_config["industry_type_response_schema"]
    effective_schema = _industry_response_schema(
        base_schema,
        allowed_industry_types,
    )
    result = await dataset_chat_json(
        dataset_name=startup_name_lower,
        queries=industry_prompt,
        prompt=(
            f"Query: {industry_prompt}\n\n"
            f"Instructions: {industry_instructions}"
        ),
        schema=effective_schema,
        reviewer=partial(
            _review_industry_type,
            allowed_industry_types=allowed_industry_types,
        ),
    )
    if result is None:
        logger.warning(
            "[%s] No industry evidence returned; defaulting to general.",
            startup_name_lower,
        )
        return "general"
    if not isinstance(result, dict):
        raise ValueError("Industry classification must be an object")
    return _industry_type_from_result(result, allowed_industry_types)

async def chapter_by_chapter(
    startup_name_lower: str,
    sorted_chapters: list,
    industry_type: str,
    dd_config: dict,
    batch_instructions: str,
) -> list[str]:
    checklists = dd_config['checklists']
    selected_checklists: list[tuple[str, str]] = []
    for chapter in sorted_chapters:
        target_key = f"{chapter}_{industry_type}"
        fallback_key = f"{chapter}_general"
        checklist_key = (
            target_key
            if target_key in checklists
            else fallback_key if fallback_key in checklists else None
        )
        if not checklist_key:
            continue

        selected_checklists.append((chapter, checklists[checklist_key]))

    async def audit_chapter(
        chapter: str,
        checklist_string: str,
    ) -> tuple[str | None, str | None]:
        try:
            audit_insight = await batch_audit(
                dataset_name=startup_name_lower,
                checklist_markdown=checklist_string,
                skill_name="dd_checks",
                llm_instructions=batch_instructions,
                status_scale=[
                    "Not Found",
                    "Critical",
                    "Borderline",
                    "Sufficient",
                    "Fine",
                ],
                missing_evidence_status="Not Found",
            )
            audit = validate_audit_document(json.loads(audit_insight.content()))
            technical_errors = audit_errors(audit)
            if technical_errors:
                details = "; ".join(
                    f"{item['number']}: {item['error']}"
                    for item in technical_errors
                )
                raise RuntimeError(
                    f"DD chapter {chapter!r} contains "
                    f"{len(technical_errors)} technical failure(s): {details}"
                )
            chapter_output = json_to_markdown_table(audit_insight)
            return f"## Chapter: {chapter}\n\n{chapter_output}\n", None
        except Exception as error:
            logger.exception(
                "[%s] Failed to process DD chapter %s",
                startup_name_lower,
                chapter,
            )
            return None, f"{chapter}: {error}"

    tasks = [
        asyncio.create_task(audit_chapter(chapter, checklist))
        for chapter, checklist in selected_checklists
    ]
    outcomes = await asyncio.gather(*tasks)
    sections = [section for section, _error in outcomes if section is not None]
    failures = [error for _section, error in outcomes if error is not None]
    if failures:
        raise RuntimeError(
            f"Failed to process {len(failures)} DD chapter(s): "
            + "; ".join(failures)
        )
    return sections

async def dd_checks(startup: str) -> InsightResult:
    """
    Performs a comprehensive M&A-style due diligence review of a startup's data room using predefined, industry-aware checklists. It automatically identifies the startup's industry, selects the appropriate checklists, searches the data room, and generates a single, complete Markdown report file in the background.
    """
    startup_slug = slugify(startup)
    from lib.startups.sources import ensure_startup_dataset

    status = await ensure_startup_dataset(startup_slug)
    startup_slug = status.dataset_slug
    storage = get_storage()
    raw_path = dataset_raw_path(startup_slug)
    if not storage.exists(raw_path):
        raise ValueError(f"Dataset for {startup_slug} not found at {raw_path}.")
    await sync_datasets([startup_slug], raise_on_error=True)
        
    config = load_repository_config()
    dd_config = config['dd_checks']
    batch_instructions = config["batch_audit"]["llm_instructions"]
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

    industry_type = await find_industry_type(startup_slug, dd_config, allowed_industry_types)
    sections = await chapter_by_chapter(
        startup_slug,
        sorted_chapters,
        industry_type,
        dd_config,
        batch_instructions,
    )
    effective_config_key = config_cache_key(
        dd_config,
        config["batch_audit"],
        config["structured_output"],
    )
    insight = InsightFile(
        dataset=startup_slug,
        skill="dd_checks",
        model=llm_model(),
        config_key=effective_config_key,
    )
    report = (
        f"# M&A Due Diligence Checks for {startup}\n\n"
        + "\n\n".join(sections)
        + "\n"
    )
    insight.save(report)
    return [insight]
