from __future__ import annotations

import json
from typing import Any

from lib.datasets.documents import resolve_document_path
from lib.datasets.ingestion import sync_datasets
from lib.datasets.paths import dataset_location, dataset_parsed_path
from lib.datasets.source import parsed_filepath
from lib.insights import InsightFile, InsightResult
from lib.json_parser import repair_json_payload
from lib.logger import get_logger
from lib.model_config import llm_model
from lib.startups.sources import ensure_startup_dataset
from lib.storage import get_storage
from lib.structured_output import (
    copy_schema,
    is_retryable_structured_error,
    json_schema_response_format,
    schema_prompt_block,
    structured_correction_feedback,
    validate_json_schema,
)
from skills.batch_audit.batch_audit import batch_audit
from skills.batch_audit.schema import audit_errors, validate_audit_document
from skills.config_load.config_load import config_key, config_load
from skills.dataset_chat.dataset_chat import dataset_chat
from skills.llm_chat.llm_chat import llm_chat

logger = get_logger(__name__)
OUTPUT_SCHEMA_VERSION = 3
_STRUCTURED_OUTPUT_ATTEMPTS = 3


def _identification_prompt(
    instructions: str,
    response_schema: dict[str, Any],
) -> str:
    return (
        f"{instructions}\n\n"
        f"{schema_prompt_block(response_schema)}"
    )


def _parse_identification(
    raw_response: str,
    response_schema: dict[str, Any],
) -> dict[str, Any]:
    result = repair_json_payload(raw_response)
    validate_json_schema(
        result,
        response_schema,
        label="SHA document-identification response",
    )
    if not isinstance(result, dict):
        raise ValueError("SHA document-identification response must be an object.")
    if any(not concern.strip() for concern in result["concerns"]):
        raise ValueError(
            "SHA document-identification concerns must contain non-blank text."
        )
    path = result["path"]
    document_match = result["document_match"]
    if (path is None) != (document_match == "None"):
        raise ValueError(
            "SHA document-identification response must use a null path if and "
            "only if document_match is None."
        )
    if path is None:
        raise ValueError(
            "No plausible Shareholders' Agreement could be identified: "
            f"{result['selection_reason']}"
        )
    return result


async def _identify_sha(
    dataset_name: str,
    sha_config: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    response_schema = sha_config["document_identification_response_schema"]
    prompt = _identification_prompt(
        sha_config["document_identification_prompt"],
        response_schema,
    )
    errors: list[str] = []
    retry_feedback = ""
    result: dict[str, Any] | None = None

    for attempt in range(1, _STRUCTURED_OUTPUT_ATTEMPTS + 1):
        try:
            raw_response = await dataset_chat(
                dataset_name=dataset_name,
                queries=sha_config["document_identification_queries"],
                prompt=prompt + retry_feedback,
                response_format=json_schema_response_format(
                    "sha_document_identification",
                    response_schema,
                ),
                max_chunks=int(
                    sha_config["document_identification_settings"][
                        "max_chunks"
                    ]
                ),
            )
            if not raw_response:
                raise ValueError(
                    "SHA document identification returned no content."
                )
            result = _parse_identification(raw_response, response_schema)
        except Exception as error:
            if not is_retryable_structured_error(error):
                raise
            errors.append(str(error))
            logger.warning(
                "[%s] SHA document identification failed on attempt "
                "%d/%d: %s",
                dataset_name,
                attempt,
                _STRUCTURED_OUTPUT_ATTEMPTS,
                error,
            )
            if attempt < _STRUCTURED_OUTPUT_ATTEMPTS:
                retry_feedback = structured_correction_feedback(error)
            continue

        break

    if result is None:
        raise RuntimeError(
            "SHA document identification failed after "
            f"{_STRUCTURED_OUTPUT_ATTEMPTS} attempts: "
            + " | ".join(errors)
        )

    path_config = sha_config["document_path_resolution"]
    min_score = float(path_config["min_score"])
    if not 0.0 <= min_score <= 100.0:
        raise ValueError(
            "sha_review.document_path_resolution.min_score must be "
            "between 0 and 100."
        )
    candidates = [
        path
        for path in [
            result["path"],
            *result["paths_for_alternative_candidates"],
        ]
        if path and path.strip()
    ]
    matches = [
        (*resolve_document_path(dataset_name, candidate), candidate, index)
        for index, candidate in enumerate(candidates)
    ]
    source_path, score, proposed_path, _index = max(
        matches,
        key=lambda item: (item[1], -item[3]),
    )
    if score < min_score:
        raise ValueError(
            "Could not resolve the proposed SHA path or any alternative "
            f"candidate with the required score of {min_score:.1f}; "
            f"best match was {source_path!r} at {score:.1f}."
        )
    if score < 100.0:
        logger.warning(
            "[%s] Resolved proposed SHA path %r to %r with score %.1f.",
            dataset_name,
            proposed_path,
            source_path,
            score,
        )
    parsed_path = parsed_filepath(dataset_parsed_path(dataset_name), source_path)
    return source_path, get_storage().read_text(parsed_path), result


def _template_response_schema(
    base_schema: dict[str, Any],
    template_keys: list[str],
) -> dict[str, Any]:
    schema = copy_schema(base_schema)
    try:
        rankings_schema = schema["properties"]["rankings"]
        rankings_schema["items"]["properties"]["template_key"]["enum"] = (
            template_keys
        )
    except (KeyError, TypeError) as error:
        raise ValueError(
            "sha_review.template_ranking_response_schema must define "
            "properties.rankings.items.properties.template_key."
        ) from error
    rankings_schema["minItems"] = len(template_keys)
    rankings_schema["maxItems"] = len(template_keys)
    return schema


def _template_ranking_prompt(
    sha_markdown: str,
    templates: dict[str, str],
    instructions: str,
    response_schema: dict[str, Any],
) -> str:
    contexts = [
        "### SHA UNDER REVIEW — CONTENT START\n\n"
        f"{sha_markdown}\n\n"
        "### SHA UNDER REVIEW — CONTENT END"
    ]
    for key, template in templates.items():
        contexts.append(
            "### REFERENCE TEMPLATE — CONTENT START\n\n"
            f"Template key: {key}\n\n{template}\n\n"
            "### REFERENCE TEMPLATE — CONTENT END"
        )
    return "\n\n".join(
        [
            instructions,
            *contexts,
            "### AUTHORITATIVE RANKING INSTRUCTIONS\n\n" + instructions,
            schema_prompt_block(response_schema),
        ]
    )


async def _rank_templates(
    sha_markdown: str,
    sha_config: dict[str, Any],
) -> tuple[str, list[dict[str, str]]]:
    templates = sha_config["reference_shas"]
    if not isinstance(templates, dict) or len(templates) < 2:
        raise ValueError("sha_review.reference_shas requires at least two templates.")
    if not all(
        isinstance(key, str)
        and key
        and isinstance(value, str)
        and value.strip()
        for key, value in templates.items()
    ):
        raise ValueError("Every SHA reference template must have a key and content.")

    template_keys = sorted(templates)
    response_schema = _template_response_schema(
        sha_config["template_ranking_response_schema"],
        template_keys,
    )
    prompt = _template_ranking_prompt(
        sha_markdown,
        {key: templates[key] for key in template_keys},
        sha_config["template_ranking_prompt"],
        response_schema,
    )
    errors: list[str] = []
    retry_feedback = ""
    ranking: list[dict[str, str]] | None = None
    returned_keys: list[str] | None = None

    for attempt in range(1, _STRUCTURED_OUTPUT_ATTEMPTS + 1):
        try:
            raw_response = await llm_chat(
                prompt=prompt + retry_feedback,
                response_format=json_schema_response_format(
                    "sha_template_ranking",
                    response_schema,
                ),
            )
            if not raw_response:
                raise ValueError("SHA template ranking returned no content.")
            ranking_result = repair_json_payload(raw_response)
            validate_json_schema(
                ranking_result,
                response_schema,
                label="SHA template-ranking response",
            )
            if not isinstance(ranking_result, dict):
                raise ValueError(
                    "SHA template-ranking response must be an object."
                )
            ranking = ranking_result["rankings"]
            if not isinstance(ranking, list):
                raise ValueError(
                    "SHA template-ranking rankings must be an array."
                )
            returned_keys = [item["template_key"] for item in ranking]
            if len(set(returned_keys)) != len(returned_keys):
                raise ValueError(
                    "SHA template ranking contains duplicate template keys."
                )
            if set(returned_keys) != set(template_keys):
                raise ValueError(
                    "SHA template ranking must include every configured "
                    "template."
                )
        except Exception as error:
            if not is_retryable_structured_error(error):
                raise
            errors.append(str(error))
            logger.warning(
                "SHA template ranking failed on attempt %d/%d: %s",
                attempt,
                _STRUCTURED_OUTPUT_ATTEMPTS,
                error,
            )
            if attempt < _STRUCTURED_OUTPUT_ATTEMPTS:
                retry_feedback = structured_correction_feedback(error)
            continue

        break

    if ranking is None or returned_keys is None:
        raise RuntimeError(
            "SHA template ranking failed after "
            f"{_STRUCTURED_OUTPUT_ATTEMPTS} attempts: "
            + " | ".join(errors)
        )

    return returned_keys[0], ranking


def _audit_instructions(
    template: str,
    *,
    sha_path: str,
    sha_markdown: str,
    reference_key: str,
    reference_markdown: str,
) -> str:
    for placeholder in (
        "{{sha_under_review}}",
        "{{reference_sha}}",
    ):
        if template.count(placeholder) != 1:
            raise ValueError(
                f"sha_review.audit_instructions must contain {placeholder} once."
            )
    sha_context = f"Originating path: {sha_path}\n\n{sha_markdown}"
    reference_context = (
        f"Reference template key: {reference_key}\n\n{reference_markdown}"
    )
    return template.replace(
        "{{sha_under_review}}",
        sha_context,
    ).replace(
        "{{reference_sha}}",
        reference_context,
    )


async def _run_audits(
    dataset_name: str,
    sha_path: str,
    sha_markdown: str,
    reference_key: str,
    sha_config: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    reference_markdown = sha_config["reference_shas"][reference_key]
    audit_settings = sha_config["audit_settings"]
    instructions = _audit_instructions(
        sha_config["audit_instructions"],
        sha_path=sha_path,
        sha_markdown=sha_markdown,
        reference_key=reference_key,
        reference_markdown=reference_markdown,
    )
    audits: list[tuple[str, dict[str, Any]]] = []
    checklists = sha_config["checklists"]
    if not isinstance(checklists, dict) or not checklists:
        raise ValueError("sha_review.checklists must contain configured checklists.")

    for checklist_key in sorted(checklists):
        [audit_insight] = await batch_audit(
            dataset_name=dataset_name,
            checklist_markdown=checklists[checklist_key],
            skill_name="sha_review",
            llm_instructions=instructions,
            status_scale=audit_settings["status_scale"],
            missing_evidence_status=audit_settings["missing_evidence_status"],
        )
        audit = validate_audit_document(json.loads(audit_insight.content()))
        failures = audit_errors(audit)
        if failures:
            details = "; ".join(
                f"{item['number']}: {item['error']}" for item in failures
            )
            raise RuntimeError(
                f"SHA checklist {checklist_key!r} contains "
                f"{len(failures)} technical failure(s): {details}"
            )
        audits.append((checklist_key, audit))
    return audits


def _summary_prompt(
    dataset_name: str,
    audits: list[tuple[str, dict[str, Any]]],
    instructions: str,
) -> str:
    context = "\n\n".join(
        "### AUDIT: "
        f"{checklist_key}\n\n"
        + json.dumps(audit, ensure_ascii=False, indent=2)
        for checklist_key, audit in audits
    )
    effective_instructions = instructions.replace(
        "{{startup}}",
        dataset_name,
    )
    return (
        "### COMBINED SHA AUDITS — CONTENT START\n\n"
        f"{context}\n\n"
        "### COMBINED SHA AUDITS — CONTENT END\n\n"
        "### AUTHORITATIVE SUMMARY INSTRUCTIONS\n\n"
        f"{effective_instructions}"
    )


def _review_output(
    summary: str,
    *,
    sha_path: str,
    document_match: str,
    concerns: list[str],
    reference_key: str,
) -> str:
    concerns_markdown = (
        "\n".join(f"- {concern.strip()}" for concern in concerns)
        if concerns
        else "No document-selection concerns were identified."
    )
    return (
        "# Shareholders' Agreement Review\n\n"
        f"- **Shareholders' Agreement:** `{sha_path}`\n"
        f"- **Document match:** {document_match}\n"
        f"- **Closest reference template:** `{reference_key}`\n\n"
        "## Document-selection concerns\n\n"
        f"{concerns_markdown}\n\n"
        "---\n\n"
        f"{summary.strip()}\n"
    )


async def sha_review(dataset_name: str) -> InsightResult:
    """Review the best-matching SHA candidate in a dataset and return a summary."""
    status = await ensure_startup_dataset(dataset_name)
    dataset_slug = status.dataset_slug
    dataset_location(dataset_slug)
    await sync_datasets([dataset_slug], raise_on_error=True)

    config = config_load()
    sha_config = config["sha_review"]
    batch_config = config["batch_audit"]
    effective_config_key = config_key(
        sha_config,
        batch_config,
        config["structured_output"],
        {"output_schema_version": OUTPUT_SCHEMA_VERSION},
    )
    output = InsightFile(
        dataset=dataset_slug,
        skill="sha_review",
        model=llm_model(),
        config_key=effective_config_key,
    )
    reusable = output.find(selection="reusable")
    if reusable is not None:
        logger.info("[%s] Using cached SHA review from %s", dataset_slug, reusable.path)
        return [reusable]

    sha_path, sha_markdown, identification = await _identify_sha(
        dataset_slug,
        sha_config,
    )
    logger.info(
        "[%s] Selected SHA %s with document match %s: %s",
        dataset_slug,
        sha_path,
        identification["document_match"],
        identification["selection_reason"],
    )
    if identification["concerns"]:
        logger.warning(
            "[%s] SHA document-selection concerns: %s",
            dataset_slug,
            "; ".join(identification["concerns"]),
        )
    reference_key, ranking = await _rank_templates(sha_markdown, sha_config)
    logger.info(
        "[%s] Selected reference SHA %s: %s",
        dataset_slug,
        reference_key,
        ranking[0]["rationale_for_rank"],
    )
    audits = await _run_audits(
        dataset_slug,
        sha_path,
        sha_markdown,
        reference_key,
        sha_config,
    )
    summary = await llm_chat(
        prompt=_summary_prompt(
            dataset_slug,
            audits,
            sha_config["summary_instructions"],
        )
    )
    if not summary or not summary.strip():
        raise ValueError("SHA review summary returned no content.")

    output.save(
        _review_output(
            summary,
            sha_path=sha_path,
            document_match=identification["document_match"],
            concerns=identification["concerns"],
            reference_key=reference_key,
        )
    )
    logger.info("[%s] SHA review saved to %s", dataset_slug, output.path)
    return [output]
