"""Stage 1: classify every dataset document for cap-table/CLA analysis."""

from __future__ import annotations

from typing import Any

from lib.captable.documents import ParsedDocument, load_parsed_documents
from lib.infrastructure.ai_text_generation import Review, generate_json
from lib.infrastructure.ai_text_generation.json import copy_schema
from lib.infrastructure.configuration import load_repository_config
from lib.infrastructure.logging import get_logger

logger = get_logger(__name__)

DOCUMENT_CLASSES = (
    "current_cap_table",
    "forecast_scenario_model",
    "share_register",
    "cla_executed",
    "cla_term_sheet",
    "cla_side_doc",
    "articles_of_association",
    "commercial_register_extract",
    "sha_or_priced_term_sheet",
    "syndicate_agreement",
    "warrant_agreement",
    "esop_psop_plan",
    "tax_ruling",
    "employment_or_advisor_agreement",
    "other",
)

CLA_CLASSES = ("cla_executed", "cla_term_sheet")


def _specialized_schema(
    base_schema: dict[str, Any],
    filenames: list[str],
) -> dict[str, Any]:
    """Pin the response to exactly one entry per dataset filename."""
    schema = copy_schema(base_schema)
    documents_schema = schema["properties"]["documents"]
    documents_schema["minItems"] = len(filenames)
    documents_schema["maxItems"] = len(filenames)
    documents_schema["items"]["properties"]["filename"]["enum"] = filenames
    return schema


def _review_classification(
    filenames: list[str],
) -> Any:
    expected = set(filenames)

    def reviewer(output: Any) -> Review[Any]:
        if not isinstance(output, dict):
            return Review(output, ("Response must be a JSON object.",))
        returned = [
            entry.get("filename")
            for entry in output.get("documents", [])
            if isinstance(entry, dict)
        ]
        if set(returned) != expected or len(returned) != len(expected):
            missing = sorted(expected - set(returned))
            extra = sorted(set(returned) - expected)
            duplicated = sorted(
                name for name in set(returned) if returned.count(name) > 1
            )
            return Review(
                output,
                (
                    "Classify each dataset file exactly once. "
                    f"Missing: {missing}; unexpected: {extra}; "
                    f"duplicated: {duplicated}.",
                ),
            )
        return Review(output)

    return reviewer


def _classification_prompt(
    prompt_template: str,
    documents: list[ParsedDocument],
    excerpt_characters: int,
) -> str:
    blocks = []
    for document in documents:
        excerpt = document.text[:excerpt_characters]
        blocks.append(
            f"### FILE: {document.filename}\n"
            f"```\n{excerpt}\n```"
        )
    return (
        f"{prompt_template.strip()}\n\n"
        f"There are exactly {len(documents)} documents.\n\n"
        + "\n\n".join(blocks)
    )


async def classify_documents(dataset_name: str) -> dict[str, Any]:
    """Classify every parsed document of the dataset.

    Returns ``{"dataset": ..., "documents": [...]}`` with one entry per
    source document, ordered like the model response.
    """
    config = load_repository_config("captable")
    settings = config["classification_settings"]
    documents = load_parsed_documents(dataset_name)
    filenames = [document.filename for document in documents]

    schema = _specialized_schema(
        config["classification_response_schema"], filenames
    )
    prompt = _classification_prompt(
        config["classification_prompt"],
        documents,
        int(settings["excerpt_characters"]),
    )
    result = await generate_json(
        prompt,
        schema,
        reviewer=_review_classification(filenames),
    )
    if not isinstance(result, dict):
        raise ValueError("Classification response must be a JSON object.")

    min_confidence = float(settings["min_confidence_warn"])
    for entry in result["documents"]:
        if float(entry["confidence"]) < min_confidence:
            logger.warning(
                "[%s] Low-confidence classification %r for %r (%.0f).",
                dataset_name,
                entry["document_class"],
                entry["filename"],
                float(entry["confidence"]),
            )
    return {"dataset": dataset_name, "documents": result["documents"]}
