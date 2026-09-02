from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from functools import partial
from typing import Any

from lib.batch_audit.checklist import ChecklistCheck, parse_checklist
from lib.batch_audit.schema import (
    AUDIT_SCHEMA_VERSION,
    audit_errors,
    validate_audit_document,
)
from lib.infrastructure.ai_text_generation import Review
from lib.infrastructure.ai_text_generation.json import copy_schema
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


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a JSON list.")
    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must contain only strings.")
    return [item.strip() for item in value if item.strip()]


def _parse_check_response(
    result: dict[str, Any],
    status_scale: list[str],
) -> dict[str, Any]:
    status = str(result.get("status", "")).strip()
    if status not in status_scale:
        raise ValueError(
            f"Invalid audit status {status!r}; expected one of {status_scale}."
        )
    rationale = result.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("rationale must be a non-empty string.")
    return {
        "status": status,
        "rationale": rationale.strip(),
        "source_documents": _string_list(
            result.get("source_documents"),
            "source_documents",
        ),
        "proposed_next_steps_and_questions": _string_list(
            result.get("proposed_next_steps_and_questions"),
            "proposed_next_steps_and_questions",
        ),
        "error": None,
    }


def _review_check_response(
    output: dict | list,
    status_scale: list[str],
) -> Review[dict | list]:
    if not isinstance(output, dict):
        return Review(output, ("Batch-audit response must be an object",))
    try:
        _parse_check_response(output, status_scale)
    except (KeyError, TypeError, ValueError) as error:
        return Review(output, (str(error),))
    return Review(output)


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


def _specialize_response_schema(
    response_schema: dict[str, Any],
    status_scale: list[str],
) -> dict[str, Any]:
    specialized = copy_schema(response_schema)
    try:
        specialized["properties"]["status"]["enum"] = status_scale
    except (KeyError, TypeError) as error:
        raise ValueError(
            "Batch-audit response schema must define properties.status."
        ) from error
    return specialized


def _missing_evidence_result(status: str) -> dict[str, Any]:
    return {
        "status": status,
        "rationale": "No relevant evidence was found in the indexed dataset.",
        "source_documents": [],
        "proposed_next_steps_and_questions": [
            "Provide or locate evidence that addresses this check."
        ],
        "error": None,
    }


def _error_result(error: Exception) -> dict[str, Any]:
    return {
        "status": None,
        "rationale": None,
        "source_documents": [],
        "proposed_next_steps_and_questions": [],
        "error": str(error),
    }


async def _run_check(
    dataset_name: str,
    check: ChecklistCheck,
    llm_instructions: str,
    response_schema: dict[str, Any],
    status_scale: list[str],
    missing_evidence_status: str,
) -> dict[str, Any]:
    try:
        result = await dataset_chat_json(
            dataset_name=dataset_name,
            queries=_retrieval_queries(check),
            prompt=_llm_check_prompt(check),
            schema=response_schema,
            reviewer=partial(
                _review_check_response,
                status_scale=status_scale,
            ),
            cacheable_prompt_prefix=_llm_prompt_prefix(llm_instructions),
        )
        if result is None:
            return _missing_evidence_result(missing_evidence_status)
        if not isinstance(result, dict):
            raise ValueError("Batch-audit response must be an object")
        return _parse_check_response(result, status_scale)
    except Exception as error:
        logger.warning(
            "[%s] Audit check %s failed: %s",
            dataset_name,
            check.number,
            error,
        )
        return _error_result(error)


async def batch_audit(
    dataset_name: str,
    checklist_markdown: str,
    *,
    skill_name: str = "batch_audit",
    llm_instructions: str | None = None,
    status_scale: list[str] | None = None,
    missing_evidence_status: str | None = None,
) -> InsightFile:
    """Run a structured Markdown checklist and save its canonical JSON Insight."""
    if llm_instructions is None:
        llm_instructions = load_repository_config(
            "batch_audit", "llm_instructions"
        )
    if status_scale is None:
        status_scale = [
            "Not Found",
            "Critical",
            "Borderline",
            "Sufficient",
            "Fine",
        ]
    if missing_evidence_status is None:
        missing_evidence_status = status_scale[0]

    checklist = parse_checklist(checklist_markdown)
    if not status_scale or any(not status for status in status_scale):
        raise ValueError("status_scale must contain at least one non-empty status.")
    if len(set(status_scale)) != len(status_scale):
        raise ValueError("status_scale must not contain duplicate statuses.")
    if missing_evidence_status not in status_scale:
        raise ValueError("missing_evidence_status must be in status_scale.")

    batch_config = load_repository_config("batch_audit")
    base_schema = batch_config["response_schema"]
    if not isinstance(base_schema, dict):
        raise ValueError("batch_audit.response_schema must be a JSON object.")
    response_schema = _specialize_response_schema(
        base_schema,
        status_scale,
    )

    model = llm_model()
    effective_config_key = config_cache_key(
        batch_config,
        load_repository_config("structured_output"),
        {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "skill_name": skill_name,
            "checklist": checklist_markdown,
            "llm_instructions": llm_instructions,
            "status_scale": status_scale,
            "missing_evidence_status": missing_evidence_status,
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
            cached_audit = validate_audit_document(
                json.loads(reusable.content())
            )
            if audit_errors(cached_audit):
                raise ValueError("The cached audit contains technical errors.")
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
                    status_scale,
                    missing_evidence_status,
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
        "status_scale": status_scale,
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
    validate_audit_document(audit)
    insight.save(json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    return insight
