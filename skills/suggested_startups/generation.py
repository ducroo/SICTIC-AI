"""Startup-profile ranking and report rendering."""

from __future__ import annotations

from dataclasses import dataclass

from lib.insights import InsightFile
from lib.infrastructure.logging import get_logger
from lib.startups.dealum.manifest import dealum_url_for_startup
from skills.ranking.ranking_rationale import ranking_rationale
from skills.ranking.ranking_top_k import ranking_top_k

logger = get_logger(__name__)


@dataclass(frozen=True)
class Suggestion:
    startup_name: str
    rank: int
    rationale: str


def compile_startup_profiles(profiles: list[InsightFile]) -> dict[str, str]:
    logger.info(
        "Compiling %d selected startup profiles for evaluation...",
        len(profiles),
    )
    compiled: dict[str, str] = {}
    for profile in profiles:
        if profile.dataset in compiled:
            raise ValueError(
                f"Duplicate startup profile ID {profile.dataset!r}."
            )
        compiled[profile.dataset] = profile.content()
    return compiled


async def generate_report(
    investor: str,
    investor_profile: str,
    startup_profiles: dict[str, str],
    objective_template: str,
    max_startups: int,
) -> str:
    objective = objective_template.replace(
        "{{investor_profile}}",
        f"=== INVESTOR PROFILE: {investor} ===\n{investor_profile}",
    )
    logger.info(
        "Ranking %d startups for %s...",
        len(startup_profiles),
        investor,
    )
    ranked_items, _actual_top_k = await ranking_top_k(
        objective=objective,
        all_profiles=startup_profiles,
        top_k=max_startups,
    )
    ranked_items = await ranking_rationale(
        ranked_items=ranked_items,
        objective=objective,
    )
    suggestions = [
        Suggestion(
            startup_name=item["id"],
            rank=item["rank"],
            rationale=item["rationale"],
        )
        for item in ranked_items
    ]
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
