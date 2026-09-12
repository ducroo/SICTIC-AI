from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from lib.batch_audit.checklist import ChecklistCheck, parse_checklist
from lib.batch_audit.schema import (
    AUDIT_SCHEMA_VERSION,
    validate_audit_document,
    validate_response_schema,
)
from lib.infrastructure.configuration import (
    config_cache_key,
    load_repository_config,
)
from lib.infrastructure.logging import get_logger
from lib.insights import InsightFile
from lib.model_config import llm_model
from lib.slugify import slugify
from skills.dataset_chat.dataset_chat import dataset_chat_json

logger = get_logger(__name__)


def _generated_at() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _retrieval_queries(check: ChecklistCheck) -> list[str]:
    queries = [check.description]
    if check.keywords:
        queries.append(
            f"{check.description}\n\nRelevant terminology: "
            + ", ".join(check.keywords)
        )
    return queries


def _llm_prompt_prefix(llm_instructions: str) -> str:
    return (
        "### AUDIT INSTRUCTIONS — START\n\n"
        f"{llm_instructions}\n\n"
        "### AUDIT INSTRUCTIONS — END"
    )


def _llm_check_prompt(check: ChecklistCheck) -> str:
    return (
        "### CURRENT CHECK — START\n\n"
        f"{check.description}\n\n"
        "### CURRENT CHECK — END"
    )


async def _run_check(
    dataset_name: str,
    check: ChecklistCheck,
    llm_instructions: str,
    response_schema: dict[str, Any],
) -> dict[str, Any]:
    try:
        result = await dataset_chat_json(
            dataset_name=dataset_name,
            queries=_retrieval_queries(check),
            prompt=_llm_check_prompt(check),
            schema=response_schema,
            cacheable_prompt_prefix=_llm_prompt_prefix(llm_instructions),
            allow_empty_retrieval=True,
        )
        if result is None:
            raise ValueError("Batch-audit returned no assessment")
        return {"result": result, "error": None}
    except Exception as error:
        logger.warning(
            "[%s] Audit check %s failed: %s",
            dataset_name,
            check.number,
            error,
        )
        return {"result": None, "error": str(error) or type(error).__name__}


async def batch_audit(
    dataset_name: str,
    checklist_markdown: str,
    *,
    skill_name: str = "batch_audit",
    response_schema: dict[str, Any],
    llm_instructions: str,
) -> InsightFile:
    """Run a structured Markdown checklist and save its canonical JSON Insight.

    Every check assesses the supplied context even when search finds no chunks.
    A lack of evidence is an assessment outcome, not a reason to skip the check.
    Search failures still produce technical errors rather than missing evidence.
    """
    validate_response_schema(response_schema)
    if not isinstance(llm_instructions, str) or not llm_instructions.strip():
        raise ValueError("llm_instructions must be a non-empty string.")
    checklist = parse_checklist(checklist_markdown)

    model = llm_model()
    effective_config_key = config_cache_key(
        load_repository_config("structured_output"),
        {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "skill_name": skill_name,
            "checklist": checklist_markdown,
            "llm_instructions": llm_instructions,
            "response_schema": response_schema,
            "allow_empty_retrieval": True,
            "numbering": [
                {
                    "chapter": chapter.number,
                    "checks": [check.number for check in chapter.checks],
                }
                for chapter in checklist.chapters
            ],
        },
    )
    insight = InsightFile(
        dataset=slugify(dataset_name),
        skill="batch_audit",
        model=model,
        identifier=f"{skill_name}-{checklist.title}",
        subdir=True,
        extension="json",
        config_key=effective_config_key,
    )
    reusable = insight.find(selection="reusable")
    if reusable is not None:
        try:
            validate_audit_document(
                json.loads(reusable.content()), require_complete=True,
            )
            logger.info(
                "[%s] Using cached structured audit from %s",
                dataset_name,
                reusable.path,
            )
            return reusable
        except (ValueError, json.JSONDecodeError) as error:
            logger.warning(
                "[%s] Ignoring invalid cached structured audit %s: %s",
                dataset_name,
                reusable.path,
                error,
            )

    checks = [
        check
        for chapter in checklist.chapters
        for check in chapter.checks
    ]
    results: dict[str, dict[str, Any]] = {}
    if checks:
        tasks = {
            check.number: asyncio.create_task(
                _run_check(
                    dataset_name,
                    check,
                    llm_instructions,
                    response_schema,
                )
            )
            for check in checks
        }
        await asyncio.gather(*tasks.values())
        results.update(
            (number, task.result())
            for number, task in tasks.items()
        )

    audit = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "skill": skill_name,
        "checklist_title": checklist.title,
        "dataset": slugify(dataset_name),
        "model": model,
        "generated_at": _generated_at(),
        "response_schema": response_schema,
        "chapters": [
            {
                "number": chapter.number,
                "title": chapter.title,
                "checks": [
                    {
                        "number": check.number,
                        "check": check.name,
                        **results[check.number],
                    }
                    for check in chapter.checks
                ],
            }
            for chapter in checklist.chapters
        ],
    }
    insight.save(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    return insight
