"""Coordinate startup suggestions from stored investor and startup profiles."""

from __future__ import annotations

import asyncio
from typing import List, Optional

from lib.datasets.paths import list_dataset_names
from lib.insights import InsightFile, InsightResult
from lib.infrastructure.logging import get_logger
from lib.model_config import llm_model
from lib.people.model import Person
from lib.infrastructure.configuration import (
    config_cache_key,
    load_repository_config,
)
from skills.suggested_startups.generation import (
    compile_startup_profiles,
    generate_report,
)
from skills.suggested_startups.inputs import (
    SuggestedStartupsConfig,
    SuggestedStartupsRequest,
    load_investor_profiles,
    load_skill_config,
    load_startup_profiles,
    resolve_request,
)

logger = get_logger(__name__)


def _prepare_outputs(
    request: SuggestedStartupsRequest,
    skill_config: SuggestedStartupsConfig,
) -> list[tuple[Person, InsightFile]]:
    request_key = config_cache_key(
        skill_config.key,
        {
            "startups": request.startups,
            "max_startups": request.max_startups,
        },
    )
    pending: list[tuple[Person, InsightFile]] = []
    for person in request.investors:
        insight = InsightFile(
            dataset=request.dataset,
            skill="suggested_startups",
            model=llm_model(),
            identifier=person.display_name,
            subdir=True,
            config_key=request_key,
        )
        pending.append((person, insight))
    return pending


async def suggested_startups(
    dataset_name: str = "sictic_members",
    startups: Optional[List[str]] = None,
    investors: Optional[List[str]] = None,
    max_startups: int = 5,
) -> InsightResult:
    """Rank stored startup profiles for canonical investors in a dataset."""
    config = load_repository_config()
    skill_config = load_skill_config(config)
    request = resolve_request(
        dataset_name,
        startups,
        investors,
        max_startups,
        config=config,
        available_startups=list_dataset_names("startups"),
    )

    startup_profiles = await load_startup_profiles(request.startups)
    pending = _prepare_outputs(request, skill_config)

    pending_people = [person for person, _insight in pending]
    investor_profiles = load_investor_profiles(
        request.dataset,
        pending_people,
    )
    compiled_startup_profiles = compile_startup_profiles(startup_profiles)

    async def generate(
        person: Person,
        insight: InsightFile,
    ) -> InsightFile:
        logger.info(
            "[%s] Processing investor: %s",
            request.dataset,
            person.display_name,
        )
        report = await generate_report(
            person.display_name,
            investor_profiles[person.linkedin_id],
            compiled_startup_profiles,
            skill_config.prompt,
            request.max_startups,
        )
        insight.save(report)
        logger.info(
            "[%s] Saved suggestions for %s to %s",
            request.dataset,
            person.display_name,
            insight.path,
        )
        return insight

    generated_results = await asyncio.gather(
        *(generate(person, insight) for person, insight in pending),
        return_exceptions=True,
    )
    generated: InsightResult = []
    failures: list[str] = []
    for (person, _insight), result in zip(pending, generated_results):
        if isinstance(result, BaseException):
            if not isinstance(result, Exception):
                raise result
            logger.error(
                "[%s] Failed to generate suggested startups for %s. "
                "No insight was saved.",
                request.dataset,
                person.display_name,
                exc_info=(type(result), result, result.__traceback__),
            )
            failures.append(f"{person.display_name}: {result}")
        else:
            generated.append(result)
    logger.info(
        "[%s] Suggested-startups summary: %d generated, %d failed.",
        request.dataset,
        len(generated),
        len(failures),
    )
    if failures:
        raise RuntimeError(
            f"Failed to generate suggestions for {len(failures)} "
            "investor(s): " + "; ".join(failures)
        )
    return generated
