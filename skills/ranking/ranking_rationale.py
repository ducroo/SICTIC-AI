from functools import partial
from typing import Any, Dict, List

from lib.infrastructure.ai_text_generation import Review, generate_json
from lib.infrastructure.ai_text_generation.json import copy_schema
from lib.infrastructure.configuration import load_repository_config


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


def _review_rationales(
    output: dict | list,
    *,
    expected_ids: list[str],
) -> Review[dict | list]:
    returned_ids = [result["id"] for result in output["results"]]
    problems = []
    if len(set(returned_ids)) != len(returned_ids):
        problems.append("Duplicate rationale IDs.")
    missing = [item for item in expected_ids if item not in returned_ids]
    if missing:
        problems.append("Missing rationale IDs: " + ", ".join(missing))
    return Review(output, tuple(problems))


async def ranking_rationale(
    ranked_items: List[Dict[str, Any]],
    objective: str,
) -> List[Dict[str, Any]]:
    """Add concise rationales while preserving canonical profile identity."""
    if not ranked_items:
        return []

    section = load_repository_config("ranking_rationale")
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
    response = await generate_json(
        prompt,
        response_schema,
        partial(_review_rationales, expected_ids=profile_ids),
    )
    rationale_lookup = {
        result["id"]: result["rationale"].strip()
        for result in response["results"]
    }

    for item in ranked_items:
        item["rationale"] = rationale_lookup[item["id"]]
    return ranked_items
