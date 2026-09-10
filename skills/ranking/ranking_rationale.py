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


def _review_rationales(
    output: dict | list,
    *,
    expected_ids: list[str],
) -> Review[dict | list]:
    try:
        if not isinstance(output, dict):
            raise ValueError("Ranking-rationale response must be an object.")
        _rationale_lookup(output["results"], expected_ids)
    except (KeyError, TypeError, ValueError) as error:
        return Review(output, (str(error),))
    return Review(output)


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
    assert isinstance(response, dict)
    rationale_lookup = _rationale_lookup(response["results"], profile_ids)

    for item in ranked_items:
        item["rationale"] = rationale_lookup[item["id"]]
    return ranked_items
