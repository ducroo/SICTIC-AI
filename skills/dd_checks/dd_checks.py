import asyncio
import json
from dataclasses import dataclass
from typing import Any

from lib.batch_audit import batch_audit
from lib.batch_audit.rendering import (
    json_to_markdown_table,
    ranked_checks_to_markdown_table,
)
from lib.batch_audit.schema import validate_audit_document
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

# Heading of the report section that lists the most important checks first.
TOP_FINDINGS_HEADING = "## Most important findings"


@dataclass(frozen=True)
class ChapterAudit:
    """One assessed DD chapter."""

    # Markdown section with the chapter's complete check table.
    section: str
    # Canonical JSON audit the section was rendered from.
    audit: InsightFile


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
    review = _review_industry_type(result)
    if review.problems:
        raise ValueError("; ".join(review.problems))
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
    return allowed_by_lower[industry_type.lower()]


def _review_industry_type(output: dict | list) -> Review[dict | list]:
    if output["industry_type"] is not None and not any(
        item.strip() for item in output["evidence"]
    ):
        return Review(output, (
            "Industry classification requires evidence when a type is selected.",
        ))
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
        reviewer=_review_industry_type,
    )
    if result is None:
        logger.warning(
            "[%s] No industry evidence returned; defaulting to general.",
            startup_name_lower,
        )
        return "general"
    return _industry_type_from_result(result, allowed_industry_types)


def audit_instructions_with_context(dd_config: dict, industry_type: str) -> str:
    """Add the startup's industry and what matters most for it to the audit instructions.

    Every check receives this text, so it only contains stable, configured
    values. A generated summary would change between runs and invalidate all
    cached chapter audits.
    """
    industry_focus = dd_config.get("industry_focus") or {}
    if industry_type not in industry_focus:
        raise ValueError(
            "dd_checks.industry_focus requires an entry for industry type "
            f"{industry_type!r}."
        )
    return (
        f"{dd_config['audit_instructions']}\n\n"
        "## Startup context\n\n"
        f"Industry type: {industry_type}\n\n"
        f"{industry_focus[industry_type]}"
    )


def _top_findings_section(
    audits: list[InsightFile],
    dd_config: dict,
) -> str:
    settings = dd_config["settings"]["top_findings"]
    minimum_importance = settings["minimum_importance"]
    maximum_count = settings["maximum_count"]
    table = ranked_checks_to_markdown_table(
        audits,
        "importance",
        minimum=minimum_importance,
        limit=maximum_count,
    )
    introduction = (
        f"Checks with an importance of at least {minimum_importance} out of "
        f"10, most important first, at most {maximum_count}. The chapter "
        "tables below list all checks."
    )
    body = table or (
        f"No check has an importance of at least {minimum_importance}."
    )
    return f"{TOP_FINDINGS_HEADING}\n\n{introduction}\n\n{body}\n"


def most_important_findings(report: str) -> str | None:
    """Return the most-important-findings section of a DD report.

    Returns None when the report has no such section, for example a manual
    report.
    """
    lines = report.splitlines()
    try:
        start = lines.index(TOP_FINDINGS_HEADING)
    except ValueError:
        return None
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].startswith("## ")
        ),
        len(lines),
    )
    return "\n".join(lines[start:end]).strip()


async def chapter_by_chapter(
    startup_name_lower: str,
    sorted_chapters: list,
    industry_type: str,
    dd_config: dict,
    batch_instructions: str,
) -> list[ChapterAudit]:
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
    ) -> tuple[ChapterAudit | None, str | None]:
        try:
            audit_insight = await batch_audit(
                dataset_name=startup_name_lower,
                checklist_markdown=checklist_string,
                skill_name="dd_checks",
                llm_instructions=batch_instructions,
                response_schema=dd_config["audit_response_schema"],
            )
            validate_audit_document(
                json.loads(audit_insight.content()), require_complete=True,
            )
            chapter_output = json_to_markdown_table(audit_insight)
            section = f"## Chapter: {chapter}\n\n{chapter_output}\n"
            return ChapterAudit(section=section, audit=audit_insight), None
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
    chapters = [chapter for chapter, _error in outcomes if chapter is not None]
    failures = [error for _chapter, error in outcomes if error is not None]
    if failures:
        raise RuntimeError(
            f"Failed to process {len(failures)} DD chapter(s): "
            + "; ".join(failures)
        )
    return chapters

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
    effective_config_key = config_cache_key(
        dd_config,
        config["structured_output"],
    )
    insight = InsightFile(
        dataset=startup_slug,
        skill="dd_checks",
        model=llm_model(),
        config_key=effective_config_key,
    )
    if reusable := insight.find(selection="reusable"):
        return [reusable]

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
    chapter_audits = await chapter_by_chapter(
        startup_slug,
        sorted_chapters,
        industry_type,
        dd_config,
        audit_instructions_with_context(dd_config, industry_type),
    )
    top_findings = _top_findings_section(
        [chapter.audit for chapter in chapter_audits],
        dd_config,
    )
    report = (
        f"# M&A Due Diligence Checks for {startup}\n\n"
        f"**Industry type:** {industry_type}\n\n"
        + "\n\n".join([top_findings, *(chapter.section for chapter in chapter_audits)])
        + "\n"
    )
    insight.save(report)
    return [insight]
