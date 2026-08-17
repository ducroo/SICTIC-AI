from typing import Any, Dict, List

from lib.structured_output import (
    copy_schema,
    json_schema_response_format,
    parse_json_response,
    schema_text,
)
from skills.config_load.config_load import config_load
from skills.llm_chat.llm_chat import llm_chat


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
        .replace("{{response_schema}}", schema_text(response_schema))
    )

    response_content = await llm_chat(
        prompt,
        response_format=json_schema_response_format(
            "profile_rationales",
            response_schema,
        ),
    )
    if not response_content:
        raise ValueError("Rationale model returned no content.")
    parsed = parse_json_response(
        response_content,
        response_schema,
        label="Ranking-rationale response",
    )
    rationale_lookup = _rationale_lookup(
        parsed["results"],
        profile_ids,
    )
    for item in ranked_items:
        item["rationale"] = rationale_lookup[item["id"]]
    return ranked_items
