from __future__ import annotations

import asyncio
import json
from typing import Any

from lib.batch_audit import batch_audit
from lib.batch_audit.schema import audit_errors, validate_audit_document
from lib.datasets.ingestion import sync_datasets
from lib.infrastructure.ai_text_generation import generate_markdown
from lib.infrastructure.configuration import config_cache_key, load_repository_config
from lib.infrastructure.logging import get_logger
from lib.insights import InsightFile, InsightResult
from lib.model_config import llm_model
from lib.people.model import Person
from lib.startups.sources import ensure_startup_dataset
from skills.person_profile.person_profile import person_profile_as_person_objects
from skills.startup_profile.startup_profile import startup_profile

logger = get_logger(__name__)
OUTPUT_SCHEMA_VERSION = 1


def _profiles_context(startup_insights: InsightResult, persons: list[Person]) -> str:
    parts = ["### STARTUP PROFILE — EVIDENCE START"]
    for insight in sorted(startup_insights, key=lambda item: item.path):
        parts.append(f"Profile artifact: {insight.path}\n\n{insight.content()}")
    parts.extend([
        "### STARTUP PROFILE — EVIDENCE END",
        "### RELATED PERSON PROFILES — EVIDENCE START",
    ])
    for person in sorted(persons, key=lambda item: (item.full_name.casefold(), item.identifier)):
        parts.append(
            f"**Person:** {person.full_name}\n\n"
            f"{person.person_profile_markdown or 'Insufficient information.'}"
        )
    if not persons:
        parts.append("No related persons were identified in the data-room evidence.")
    parts.append("### RELATED PERSON PROFILES — EVIDENCE END")
    return "\n\n".join(parts)


async def _run_audits(
    dataset_slug: str,
    shared_context: str,
    config: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    checklists = config["checklists"]
    if not isinstance(checklists, dict) or not checklists:
        raise ValueError("team_profile_revised.checklists requires configured checklists.")
    instructions = shared_context + "\n\n" + config["audit_instructions"]
    settings = config["audit_settings"]
    keys = sorted(checklists)
    results = await asyncio.gather(*(
        batch_audit(
            dataset_name=dataset_slug,
            checklist_markdown=checklists[key],
            skill_name="team_profile_revised",
            llm_instructions=instructions,
            status_scale=settings["status_scale"],
            missing_evidence_status=settings["missing_evidence_status"],
            allow_empty_retrieval=True,
        )
        for key in keys
    ))
    audits = []
    for key, result in zip(keys, results):
        audit = validate_audit_document(json.loads(result.content()))
        failures = audit_errors(audit)
        if failures:
            details = "; ".join(f"{item['number']}: {item['error']}" for item in failures)
            raise RuntimeError(f"Team checklist {key!r} contains technical failures: {details}")
        audits.append((key, audit))
    return audits


def _summary_prompt(
    dataset_slug: str,
    audits: list[tuple[str, dict[str, Any]]],
    instructions: str,
) -> str:
    context = "\n\n".join(
        f"### CATEGORY AUDIT: {key}\n\n"
        + json.dumps(audit, ensure_ascii=False, indent=2)
        for key, audit in audits
    )
    return (
        "### COMPLETED TEAM AUDITS — EVIDENCE START\n\n"
        f"{context}\n\n"
        "### COMPLETED TEAM AUDITS — EVIDENCE END\n\n"
        "### AUTHORITATIVE SYNTHESIS INSTRUCTIONS\n\n"
        + instructions.replace("{{startup}}", dataset_slug)
    )


async def team_profile_revised(startup_name: str) -> InsightResult:
    """Assess sectioned team checklists, then synthesize each category."""
    status = await ensure_startup_dataset(startup_name)
    dataset_slug = status.dataset_slug
    await sync_datasets([dataset_slug], raise_on_error=True)
    config = load_repository_config()
    team_config = config["team_profile_revised"]

    # Dependencies own their artifact caches. Materialize them before checking
    # the final cache so changes to a supplied profile also invalidate the result.
    startup_insights = await startup_profile(dataset_slug)
    persons = await person_profile_as_person_objects(
        dataset_slug,
        names=None,
    )
    shared_context = _profiles_context(startup_insights, persons)
    output = InsightFile(
        dataset=dataset_slug,
        skill="team_profile_revised",
        model=llm_model(),
        config_key=config_cache_key(
            team_config,
            config["batch_audit"],
            config["structured_output"],
            config["startup_profile"],
            config["person_profile"],
            shared_context,
            {"output_schema_version": OUTPUT_SCHEMA_VERSION},
        ),
    )
    reusable = output.find(selection="reusable")
    if reusable is not None:
        logger.info("[%s] Using cached revised team profile from %s", dataset_slug, reusable.path)
        return [reusable]

    logger.info("[%s] Assessing team checklists", dataset_slug)
    audits = await _run_audits(dataset_slug, shared_context, team_config)
    summary = await generate_markdown(
        _summary_prompt(dataset_slug, audits, team_config["summary_instructions"])
    )
    if not summary or not summary.strip():
        raise ValueError("Team-profile synthesis returned an empty response.")
    output.save(f"# Team Profile — {dataset_slug}\n\n{summary.strip()}\n")
    logger.info("[%s] Revised team profile saved to %s", dataset_slug, output.path)
    return [output]
