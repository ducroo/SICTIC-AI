from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from lib.insights import InsightFile
from lib.json_parser import repair_json_payload
from lib.logger import get_logger
from lib.model_config import llm_model
from lib.slugify import slugify
from lib.structured_output import (
    copy_schema,
    json_schema_response_format,
    schema_prompt_block,
    validate_json_schema,
)
from skills.batch_audit.checklist import ChecklistCheck, parse_checklist
from skills.batch_audit.schema import (
    AUDIT_SCHEMA_VERSION,
    audit_errors,
    validate_audit_document,
)
from skills.dataset_chat.dataset_chat import _fallback_trigger, dataset_chat
from skills.config_load.config_load import config_key, config_load

logger = get_logger(__name__)

MAX_ATTEMPTS = 3


def _generated_at() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a JSON list.")
    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must contain only strings.")
    return [item.strip() for item in value if item.strip()]


def _parse_check_response(
    raw_response: str,
    response_schema: dict[str, Any],
    status_scale: list[str],
) -> dict[str, Any]:
    result = repair_json_payload(raw_response)
    validate_json_schema(
        result,
        response_schema,
        label="Batch-audit response",
    )
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


def _retrieval_queries(check: ChecklistCheck) -> list[str]:
    queries = [check.description]
    if check.keywords:
        queries.append(
            f"{check.description}\n\nRelevant terminology: "
            + ", ".join(check.keywords)
        )
    return queries


def _llm_prompt(
    check: ChecklistCheck,
    llm_instructions: str,
    response_schema: dict[str, Any],
) -> str:
    return (
        _llm_prompt_prefix(llm_instructions, response_schema)
        + "\n\n"
        + _llm_check_prompt(check)
    )


def _llm_prompt_prefix(
    llm_instructions: str,
    response_schema: dict[str, Any],
) -> str:
    instructions = (
        f"{llm_instructions}\n\n{schema_prompt_block(response_schema)}"
    )
    return (
        "### AUDIT INSTRUCTIONS — START\n\n"
        f"{instructions}\n\n"
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
    errors: list[str] = []
    prompt_prefix = _llm_prompt_prefix(llm_instructions, response_schema)
    check_prompt = _llm_check_prompt(check)
    retry_feedback = ""

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw_response = await dataset_chat(
                dataset_name=dataset_name,
                queries=_retrieval_queries(check),
                prompt=check_prompt + retry_feedback,
                cacheable_prompt_prefix=prompt_prefix,
                strict_insufficient_context=False,
                response_format=json_schema_response_format(
                    "batch_audit_check",
                    response_schema,
                ),
            )
            if not raw_response:
                raise ValueError("Audit model returned no content.")
            if raw_response.strip() == _fallback_trigger():
                return _missing_evidence_result(missing_evidence_status)
            return _parse_check_response(
                raw_response,
                response_schema,
                status_scale,
            )
        except Exception as error:
            errors.append(str(error))
            logger.warning(
                "[%s] Audit check %s failed on attempt %d/%d: %s",
                dataset_name,
                check.number,
                attempt,
                MAX_ATTEMPTS,
                error,
            )
            if attempt < MAX_ATTEMPTS:
                retry_feedback = (
                    "\n\n### CORRECTION REQUIRED\n\n"
                    f"Your previous response was invalid: {error}\n"
                    "Try again and return only a JSON object matching "
                    "the schema."
                )
    return _error_result(
        RuntimeError(
            f"Audit check failed after {MAX_ATTEMPTS} attempts: "
            + " | ".join(errors)
        )
    )


async def batch_audit_json(
    *,
    dataset_name: str,
    skill_name: str,
    checklist_markdown: str,
    llm_instructions: str,
    status_scale: list[str],
    missing_evidence_status: str,
) -> InsightFile:
    """Run a structured Markdown checklist and save its canonical JSON Insight."""
    checklist = parse_checklist(checklist_markdown)
    if not status_scale or any(not status for status in status_scale):
        raise ValueError("status_scale must contain at least one non-empty status.")
    if len(set(status_scale)) != len(status_scale):
        raise ValueError("status_scale must not contain duplicate statuses.")
    if missing_evidence_status not in status_scale:
        raise ValueError("missing_evidence_status must be in status_scale.")

    batch_config = config_load()["batch_audit"]
    base_schema = batch_config["response_schema"]
    if not isinstance(base_schema, dict):
        raise ValueError("batch_audit.response_schema must be a JSON object.")
    response_schema = _specialize_response_schema(
        base_schema,
        status_scale,
    )

    model = llm_model()
    effective_config_key = config_key(
        batch_config,
        config_load()["structured_output"],
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
        first_check, *remaining_checks = checks
        # Run one complete check first to warm any provider-side prompt-prefix
        # cache before submitting the remaining checks concurrently.
        # TODO(2026-12): Reassess Ollama/MLX prefix-cache behavior under
        # concurrent batch-audit workloads.
        results[first_check.number] = await _run_check(
            dataset_name,
            first_check,
            llm_instructions,
            response_schema,
            status_scale,
            missing_evidence_status,
        )
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
            for check in remaining_checks
        }
        if tasks:
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
