from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lib.infrastructure.ai_text_generation import Review, generate_json
from lib.infrastructure.ai_text_generation.json import (
    parse_json_response,
    validate_json_schema,
)
from lib.infrastructure.configuration import config_cache_key, load_repository_config
from lib.infrastructure.logging import get_logger
from lib.insights import InsightFile, InsightResult
from lib.model_config import llm_model
from lib.startups.identity import canonical_startup_slug

logger = get_logger(__name__)

SECTION_ORDER = ["Team", "Business opportunity", "Product", "Documentation"]


def _find_jury_rating_report(startup_slug: str) -> InsightFile:
    try:
        report = InsightFile(
            dataset=startup_slug,
            skill="jury_rating",
            model=llm_model(),
        ).find(selection="any")
    except FileNotFoundError:
        report = None
    if report is None:
        raise ValueError(
            f"No saved rating report found for '{startup_slug}'. "
            f"Create a jury_rating report for {startup_slug} first."
        )
    return report


def _render_sections(sections: list[dict[str, Any]]) -> str:
    """Render validated synthesis as the jury-facing Markdown briefing."""
    by_name = {section["name"]: section for section in sections}
    lines: list[str] = []
    for name in SECTION_ORDER:
        section = by_name[name]
        lines.append(f"## {name}")
        lines.append("")
        lines.append(section["summary"].strip())
        lines.append("")
        lines.append("**Questions for the jury**")
        lines.append("")
        for question in section["jury_questions"]:
            lines.append(f"* {question}")
        if not section["jury_questions"]:
            lines.append("* None identified in the saved report.")
        lines.append("")
        lines.append("**Evidence excerpts from the saved report**")
        lines.append("")
        for item in section["evidence"]:
            lines.append(f"* {item.strip()}")
        lines.append("")
    return "\n".join(lines).strip()


def _section_list(result: object) -> list[dict[str, Any]]:
    if not isinstance(result, Mapping):
        raise ValueError("Jury priorities response must be a JSON object.")
    sections = result.get("sections")
    if not isinstance(sections, list):
        raise ValueError("Jury priorities response must contain sections.")
    names: list[str] = []
    for section in sections:
        name = section.get("name") if isinstance(section, Mapping) else None
        names.append(name if isinstance(name, str) else "")
    if len(names) != len(sections) or sorted(names) != sorted(SECTION_ORDER):
        raise ValueError(
            f"Expected exactly the sections {SECTION_ORDER}, got {names}."
        )
    return [dict(section) for section in sections]


def _validate_report_evidence(
    sections: list[dict[str, Any]], source_report: str
) -> None:
    """Require every section to cite at least one exact report excerpt."""
    for section in sections:
        name = section["name"]
        evidence = section.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError(
                f"Section {name!r} must contain report-backed evidence excerpts."
            )
        for excerpt in evidence:
            if not isinstance(excerpt, str) or not excerpt.strip():
                raise ValueError(
                    f"Section {name!r} contains an empty evidence excerpt."
                )
            excerpt = excerpt.strip()
            if excerpt not in source_report:
                raise ValueError(
                    f"Evidence excerpt for section {name!r} is not present "
                    "in the saved report."
                )


def _validated_sections(result: object, source_report: str) -> list[dict[str, Any]]:
    sections = _section_list(result)
    _validate_report_evidence(sections, source_report)
    return sections


def _review_report(result: dict | list, source_report: str) -> Review[dict | list]:
    try:
        _validated_sections(result, source_report)
    except ValueError as error:
        return Review(output=result, problems=(str(error),))
    return Review(output=result)


def _parse_sections(
    raw_response: str | Mapping[str, Any], response_schema: dict[str, Any]
) -> list[dict[str, Any]]:
    """Parse and structurally validate a standalone model response."""
    if isinstance(raw_response, str):
        result = parse_json_response(raw_response, response_schema)
    else:
        result = dict(raw_response)
        validate_json_schema(
            result,
            response_schema,
            label="Jury priorities response",
        )
    return _section_list(result)


async def jury_priorities(startup: str) -> InsightResult:
    """Synthesize a saved rating report into a non-ratable jury briefing."""
    startup_slug = canonical_startup_slug(startup)
    source_insight = _find_jury_rating_report(startup_slug)
    source_report = source_insight.content()
    if not source_report.strip():
        raise ValueError(
            f"The saved rating report for '{startup_slug}' is empty. "
            f"Create a jury_rating report for {startup_slug} again."
        )

    config = load_repository_config("jury_priorities")
    instructions = config["llm_instructions"].replace("{{startup}}", startup)
    response_schema = config["response_schema"]
    effective_config_key = config_cache_key(
        instructions,
        response_schema,
        source_report,
    )
    output_insight = InsightFile(
        dataset=startup_slug,
        skill="jury_priorities",
        model=llm_model(),
        config_key=effective_config_key,
    )
    reusable = output_insight.find(selection="reusable")
    if reusable is not None:
        logger.info(
            "[%s] Using cached jury priorities from %s",
            startup_slug,
            reusable.path,
        )
        return [reusable]

    prompt = (
        "### SAVED RATING REPORT START ###\n\n"
        f"{source_report}\n\n"
        "### SAVED RATING REPORT END ###\n\n"
        "### INSTRUCTIONS ###\n\n"
        f"{instructions}"
    )
    result = await generate_json(
        prompt,
        response_schema,
        reviewer=lambda value: _review_report(value, source_report),
    )
    sections = _validated_sections(result, source_report)
    report = f"# Jury briefing: {startup}\n\n" + _render_sections(sections)
    output_insight.save(report.strip())
    logger.info("[%s] Jury priorities saved to %s", startup_slug, output_insight.path)
    return [output_insight]
