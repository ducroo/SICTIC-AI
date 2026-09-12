from __future__ import annotations

import asyncio
import json
from functools import partial
from typing import Any

from lib.batch_audit import batch_audit
from lib.batch_audit.schema import validate_audit_document
from lib.datasets.documents import resolve_document_path
from lib.datasets.ingestion import sync_datasets
from lib.datasets.paths import dataset_location, dataset_parsed_path
from lib.datasets.source import parsed_filepath
from lib.infrastructure.ai_text_generation import (
    Review,
    generate_json,
    generate_markdown,
)
from lib.infrastructure.ai_text_generation.json import copy_schema
from lib.infrastructure.configuration import (
    config_cache_key,
    load_repository_config,
)
from lib.infrastructure.logging import get_logger
from lib.insights import InsightFile, InsightResult
from lib.model_config import llm_model
from lib.startups.sources import ensure_startup_dataset
from lib.storage import get_storage
from skills.dataset_chat.dataset_chat import dataset_chat_json

logger = get_logger(__name__)
OUTPUT_SCHEMA_VERSION = 3


def _identification_prompt(instructions: str) -> str:
    return instructions


def _review_identification(output: dict | list) -> Review[dict | list]:
    if output["path"] is None:
        return Review(output, (
            "No plausible Shareholders' Agreement could be identified: "
            f"{output['selection_reason']}",
        ))
    return Review(output)


async def _identify_sha(
    dataset_name: str,
    sha_config: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    response_schema = sha_config["document_identification_response_schema"]
    result = await dataset_chat_json(
        dataset_name=dataset_name,
        queries=sha_config["document_identification_queries"],
        prompt=_identification_prompt(
            sha_config["document_identification_prompt"]
        ),
        schema=response_schema,
        reviewer=_review_identification,
        max_chunks=int(
            sha_config["document_identification_settings"]["max_chunks"]
        ),
    )
    if result is None:
        raise ValueError("No plausible Shareholders' Agreement was found")

    path_config = sha_config["document_path_resolution"]
    min_score = float(path_config["min_score"])
    if not 0.0 <= min_score <= 100.0:
        raise ValueError(
            "sha_review.document_path_resolution.min_score must be "
            "between 0 and 100."
        )
    proposed_path = result["path"]
    source_path, score = resolve_document_path(dataset_name, proposed_path)
    if score < min_score:
        raise ValueError(
            f"Could not resolve the LLM-selected SHA path {proposed_path!r} "
            f"with the required score of {min_score:.1f}; "
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
        ]
    )


def _review_template_ranking(
    output: dict | list,
    template_keys: list[str],
) -> Review[dict | list]:
    returned_keys = [item["template_key"] for item in output["rankings"]]
    problems: list[str] = []
    if len(set(returned_keys)) != len(returned_keys):
        problems.append("SHA template ranking contains duplicate template keys")
    if set(returned_keys) != set(template_keys):
        problems.append("SHA template ranking must include every configured template")
    return Review(output, tuple(problems))


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
    )
    ranking_result = await generate_json(
        prompt,
        response_schema,
        reviewer=partial(
            _review_template_ranking,
            template_keys=template_keys,
        ),
    )
    ranking = ranking_result["rankings"]
    returned_keys = [item["template_key"] for item in ranking]

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
    instructions = _audit_instructions(
        sha_config["audit_instructions"],
        sha_path=sha_path,
        sha_markdown=sha_markdown,
        reference_key=reference_key,
        reference_markdown=reference_markdown,
    )
    checklists = sha_config["checklists"]
    if not isinstance(checklists, dict) or not checklists:
        raise ValueError("sha_review.checklists must contain configured checklists.")

    checklist_keys = sorted(checklists)
    tasks = {
        checklist_key: asyncio.create_task(
            batch_audit(
                dataset_name=dataset_name,
                checklist_markdown=checklists[checklist_key],
                skill_name="sha_review",
                llm_instructions=instructions,
                response_schema=sha_config["audit_response_schema"],
            )
        )
        for checklist_key in checklist_keys
    }
    results = await asyncio.gather(*tasks.values())

    audits: list[tuple[str, dict[str, Any]]] = []
    for checklist_key, audit_insight in zip(checklist_keys, results):
        audit = validate_audit_document(
            json.loads(audit_insight.content()), require_complete=True,
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

    config = load_repository_config()
    sha_config = config["sha_review"]
    effective_config_key = config_cache_key(
        sha_config,
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
    summary = await generate_markdown(
        _summary_prompt(
            dataset_slug,
            audits,
            sha_config["summary_instructions"],
        )
    )

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
