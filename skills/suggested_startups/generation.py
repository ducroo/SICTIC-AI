"""Prompt construction, LLM execution, and report rendering."""

from __future__ import annotations

import json

from lib.insights import InsightFile
from lib.logger import get_logger
from lib.startups.dealum.manifest import dealum_url_for_startup
from skills.llm_chat.llm_chat import llm_chat
from skills.suggested_startups.response import (
    Suggestion,
    parse_suggestions,
    response_format,
    specialize_schema,
)

logger = get_logger(__name__)


def compile_startup_profiles(profiles: list[InsightFile]) -> str:
    logger.info(
        "Compiling %d selected startup profiles for evaluation...",
        len(profiles),
    )
    return "\n".join(
        f"STARTUP: {profile.dataset}\n{profile.content()}\n"
        for profile in profiles
    )


async def generate_report(
    investor: str,
    investor_profile: str,
    startup_context: str,
    prompt_template: str,
    response_schema: dict,
    candidate_startups: list[str],
    max_startups: int,
) -> str:
    schema = specialize_schema(
        response_schema,
        candidate_startups,
        max_startups,
    )
    prompt = (
        prompt_template.replace(
            "{{investor_profile}}",
            f"=== INVESTOR PROFILE: {investor} ===\n{investor_profile}",
        )
        .replace("{{startup_profiles}}", startup_context)
        .replace(
            "{{response_schema}}",
            json.dumps(schema, ensure_ascii=False, indent=2),
        )
        .replace("{{max_startups}}", str(max_startups))
    )
    logger.info("Ranking startups for %s...", investor)
    raw_response = await llm_chat(
        prompt=prompt,
        response_format=response_format(schema),
    )
    if not raw_response:
        raise ValueError(
            f"Suggested-startups model returned no content for {investor}."
        )
    try:
        suggestions = parse_suggestions(
            raw_response,
            schema,
            candidate_startups,
            max_startups,
        )
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"Invalid suggested-startups response for {investor}: {error}"
        ) from error
    return render_report(investor, suggestions)


def render_report(investor: str, suggestions: list[Suggestion]) -> str:
    rows = []
    for suggestion in suggestions:
        startup = suggestion.startup_name.replace("|", "\\|")
        dealum_url = dealum_url_for_startup(suggestion.startup_name)
        dealum_link = (
            f"[Open in Dealum]({dealum_url})" if dealum_url else "—"
        )
        rationale = suggestion.rationale.replace("\n", " ").replace(
            "|", "\\|"
        )
        rows.append(f"| {startup} | {dealum_link} | {rationale} |")
    return (
        f"# Startup Suggestions for {investor}\n\n"
        "| Startup | Dealum | Rationale |\n"
        "|---|---|---|\n"
        + "\n".join(rows)
    )
