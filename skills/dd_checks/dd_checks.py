import re

from lib.model_config import llm_model
from lib.insights import InsightFile, InsightResult
from lib.storage import get_storage
from skills.config_load.config_load import config_load
from skills.batch_audit.batch_audit import batch_audit
from skills.batch_audit.rendering import json_to_markdown_table
from skills.dataset_chat.dataset_chat import dataset_chat
from lib.slugify import slugify
from lib.logger import get_logger
from lib.datasets.ingestion import sync_datasets
from lib.datasets.paths import dataset_raw_path

logger = get_logger(__name__)


def parse_industry_type(response: str, allowed_industry_types: set[str]) -> str:
    """Parse the explicit industry classification from the LLM response."""
    allowed_by_lower = {item.lower(): item for item in allowed_industry_types}
    match = re.search(r"(?im)^\s*industry\s+type\s*:\s*([A-Za-z][A-Za-z -]*)", response or "")
    if match:
        candidate = match.group(1).strip().split()[0].lower()
        if candidate in allowed_by_lower:
            return allowed_by_lower[candidate]

    stripped = (response or "").strip().lower()
    if stripped in allowed_by_lower:
        return allowed_by_lower[stripped]

    logger.warning(f"Could not parse industry type from response; defaulting to general: {response}")
    return allowed_by_lower.get("general", "general")


async def find_industry_type(startup_name_lower: str, dd_config: dict, allowed_industry_types: set) -> str:
    industry_prompt = dd_config['industry_type_query']
    industry_instructions = dd_config['industry_type_llm_instructions']
    industry_response = await dataset_chat(
        dataset_name=startup_name_lower,
        queries=industry_prompt,
        prompt=(
            f"Query: {industry_prompt}\n\n"
            f"Instructions: {industry_instructions}"
        ),
    )
    
    logger.info(f"[{startup_name_lower}] Raw Industry Type LLM Response: {industry_response}")
    return parse_industry_type(industry_response or "", allowed_industry_types)

async def chapter_by_chapter(
    startup_name_lower: str,
    sorted_chapters: list,
    industry_type: str,
    dd_config: dict,
    batch_instructions: str,
) -> list[str]:
    checklists = dd_config['checklists']
    sections = []
    for chapter in sorted_chapters:
        target_key = f"{chapter}_{industry_type}"
        fallback_key = f"{chapter}_general"
        checklist_key = target_key if target_key in checklists else (fallback_key if fallback_key in checklists else None)
        if not checklist_key:
            continue
            
        checklist_string = checklists[checklist_key]
        try:
            audit_results = await batch_audit(
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
            [audit_insight] = audit_results
            chapter_output = json_to_markdown_table(audit_insight)
            sections.append(f"## Chapter: {chapter}\n\n{chapter_output}\n")
        except Exception as e:
            sections.append(
                f"## Chapter: {chapter}\n\n"
                f"**Error:** Failed to process chapter due to: {e}\n"
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
        
    config = config_load()
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
    config_key = (
        dd_config["industry_type_query"]
        + dd_config["industry_type_llm_instructions"]
        + batch_instructions
        + "\n".join(
            f"{key}:{value}"
            for key, value in sorted(checklists.items())
        )
    )
    insight = InsightFile(
        dataset=startup_slug,
        skill="dd_checks",
        model=llm_model(),
        config_key=config_key,
    )
    report = (
        f"# M&A Due Diligence Checks for {startup}\n\n"
        + "\n\n".join(sections)
        + "\n"
    )
    insight.save(report)
    return [insight]
