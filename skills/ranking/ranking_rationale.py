from typing import Any, Dict, List

from lib.json_parser import repair_json_payload
from lib.logger import get_logger
from lib.structured_output import (
    copy_schema,
    is_retryable_structured_error,
    json_schema_response_format,
    schema_prompt_block,
    structured_correction_feedback,
    validate_json_schema,
)
from skills.config_load.config_load import config_load
from skills.llm_chat.llm_chat import llm_chat

logger = get_logger(__name__)
_STRUCTURED_OUTPUT_ATTEMPTS = 3


def _specialize_schema(
    response_schema: dict[str, Any],
    profile_ids: list[str],
) -> dict[str, Any]:
    specialized = copy_schema(response_schema)
    try:
        results = specialized["properties"]["results"]
        results["minItems"] = len(profile_ids)
        results["maxItems"] = len(profile_ids)
        results["items"]["properties"]["id"]["enum"] = profile_ids
    except (KeyError, TypeError) as error:
        raise ValueError(
            "ranking_rationale.response_schema must define "
            "properties.results.items.properties.id."
        ) from error
    return specialized


def _rationale_lookup(
    results: list[dict[str, Any]],
    expected_ids: list[str],
) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for result in results:
        profile_id = result["id"]
        if profile_id in lookup:
            raise ValueError(f"Duplicate rationale ID {profile_id!r}.")
        rationale = result["rationale"].strip()
        if not rationale:
            raise ValueError(f"Rationale for {profile_id!r} is empty.")
        lookup[profile_id] = rationale
    if set(lookup) != set(expected_ids):
        missing = [item for item in expected_ids if item not in lookup]
        raise ValueError("Missing rationale IDs: " + ", ".join(missing))
    return lookup


async def ranking_rationale(
    ranked_items: List[Dict[str, Any]],
    objective: str,
) -> List[Dict[str, Any]]:
    """Add concise rationales while preserving canonical profile identity."""
    if not ranked_items:
        return []

    section = config_load()["ranking_rationale"]
    profile_ids = [item["id"] for item in ranked_items]
    response_schema = _specialize_schema(
        section["response_schema"],
        profile_ids,
    )
    profiles_text = "\n\n---\n\n".join(
        f"### Rank {item['rank']} | Profile ID: {item['id']}\n\n"
        f"{item.get('text', 'Content missing.')}"
        for item in ranked_items
    )
    prompt = (
        section["rationale_instructions"]
        .replace("{{objective}}", objective)
        .replace("{{profiles_text}}", profiles_text)
    )
    prompt += "\n\n" + schema_prompt_block(response_schema)

    errors: list[str] = []
    retry_feedback = ""
    rationale_lookup: dict[str, str] | None = None

    for attempt in range(1, _STRUCTURED_OUTPUT_ATTEMPTS + 1):
        try:
            response_content = await llm_chat(
                prompt + retry_feedback,
                response_format=json_schema_response_format(
                    "profile_rationales",
                    response_schema,
                ),
            )
            if not response_content:
                raise ValueError("Rationale model returned no content.")
            parsed = repair_json_payload(response_content)
            validate_json_schema(
                parsed,
                response_schema,
                label="Ranking-rationale response",
            )
            rationale_lookup = _rationale_lookup(
                parsed["results"],
                profile_ids,
            )
        except Exception as error:
            if not is_retryable_structured_error(error):
                raise
            errors.append(str(error))
            logger.warning(
                "Ranking rationale failed on attempt %d/%d: %s",
                attempt,
                _STRUCTURED_OUTPUT_ATTEMPTS,
                error,
            )
            if attempt < _STRUCTURED_OUTPUT_ATTEMPTS:
                retry_feedback = structured_correction_feedback(error)
            continue

        break

    if rationale_lookup is None:
        raise RuntimeError(
            "Ranking rationale failed after "
            f"{_STRUCTURED_OUTPUT_ATTEMPTS} attempts: "
            + " | ".join(errors)
        )

    for item in ranked_items:
        item["rationale"] = rationale_lookup[item["id"]]
    return ranked_items
