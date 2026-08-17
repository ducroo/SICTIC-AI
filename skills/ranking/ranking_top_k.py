import asyncio
import random
from typing import Any, Dict, List, Tuple

from lib.logger import get_logger
from lib.structured_output import (
    copy_schema,
    json_schema_response_format,
    parse_json_response,
    schema_text,
)
from skills.config_load.config_load import config_load
from skills.llm_chat.llm_chat import llm_chat

logger = get_logger(__name__)

DEFAULT_BATCH_SIZE = 16


def _specialize_schema(
    response_schema: dict[str, Any],
    profile_ids: list[str],
) -> dict[str, Any]:
    specialized = copy_schema(response_schema)
    try:
        ranked_ids = specialized["properties"]["ranked_profiles_ids"]
        ranked_ids["items"]["enum"] = profile_ids
        ranked_ids["minItems"] = len(profile_ids)
        ranked_ids["maxItems"] = len(profile_ids)
    except (KeyError, TypeError) as error:
        raise ValueError(
            "ranking_top_k.response_schema must define "
            "properties.ranked_profiles_ids.items."
        ) from error
    return specialized


def _validate_ranked_ids(
    ranked_ids: list[str],
    expected_ids: list[str],
) -> list[str]:
    if len(set(ranked_ids)) != len(ranked_ids):
        raise ValueError("Top-k ranking contains duplicate profile IDs.")
    if set(ranked_ids) != set(expected_ids):
        missing = [item for item in expected_ids if item not in ranked_ids]
        unexpected = [item for item in ranked_ids if item not in expected_ids]
        raise ValueError(
            "Top-k ranking IDs do not match the candidates; "
            f"missing={missing}, unexpected={unexpected}."
        )
    return ranked_ids


async def rank_chunk(objective: str, profiles: Dict[str, str]) -> List[str]:
    """Rank a small set of profiles and return all IDs best to worst."""
    profile_ids = list(profiles.keys())
    if len(profile_ids) <= 1:
        return profile_ids

    section = config_load()["ranking_top_k"]
    response_schema = _specialize_schema(
        section["response_schema"],
        profile_ids,
    )
    profiles_text = "\n\n".join(
        f"ID: {profile_id}\n{profiles[profile_id]}"
        for profile_id in profile_ids
    )
    prompt = (
        section["ranking_instructions"]
        .replace("{{profiles_text}}", profiles_text)
        .replace("{{objective}}", objective)
        .replace("{{n_profiles}}", str(len(profiles)))
        .replace("{{IDs_profiles}}", ", ".join(profile_ids))
        .replace("{{response_schema}}", schema_text(response_schema))
    )

    response_content = await llm_chat(
        prompt,
        response_format=json_schema_response_format(
            "ranked_profile_ids",
            response_schema,
        ),
    )
    if not response_content:
        raise ValueError("Ranking model returned no content.")
    parsed = parse_json_response(
        response_content,
        response_schema,
        label="Top-k ranking response",
    )
    return _validate_ranked_ids(
        parsed["ranked_profiles_ids"],
        profile_ids,
    )


async def ranking_top_k(
    objective: str,
    all_profiles: Dict[str, str],
    top_k: int = 8,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Tuple[List[Dict[str, Any]], int]:
    """Find top profiles using a bucketed Swiss tournament."""
    if top_k < 1:
        raise ValueError("top_k must be at least 1.")
    if batch_size < 2 or batch_size % 2:
        raise ValueError("batch_size must be an even integer of at least 2.")

    logger.info(
        "Starting Swiss tournament ranking_top_k with %d candidates, "
        "top_k=%d, and batch_size=%d.",
        len(all_profiles),
        top_k,
        batch_size,
    )
    active_profiles = list(all_profiles.keys())
    random.shuffle(active_profiles)
    advancing_bucket_count = batch_size // 2
    buckets = [[] for _ in range(advancing_bucket_count)]
    for index, profile_id in enumerate(active_profiles):
        buckets[index % advancing_bucket_count].append(profile_id)

    while True:
        total_remaining = sum(len(bucket) for bucket in buckets)
        logger.info("Swiss iteration: %d active profiles.", total_remaining)
        chunks = []
        current_chunk = []
        while any(buckets):
            for bucket in buckets:
                for _ in range(2):
                    if bucket:
                        current_chunk.append(bucket.pop(0))
            if len(current_chunk) == batch_size or (
                not any(buckets) and current_chunk
            ):
                chunks.append(current_chunk)
                current_chunk = []

        chunk_rankings = await asyncio.gather(
            *(
                rank_chunk(
                    objective,
                    {profile_id: all_profiles[profile_id] for profile_id in chunk},
                )
                for chunk in chunks
            )
        )
        temp_buckets = [[] for _ in range(batch_size)]
        for ranked_chunk in chunk_rankings:
            count = len(ranked_chunk)
            for index, profile_id in enumerate(ranked_chunk):
                bucket_index = int(index * batch_size / count) if count else 0
                temp_buckets[min(batch_size - 1, bucket_index)].append(
                    profile_id
                )

        total_in_temp = sum(len(bucket) for bucket in temp_buckets)
        if total_in_temp < 2 * top_k:
            logger.info(
                "Stopping condition met: %d profiles is less than "
                "2 * top_k (%d).",
                total_in_temp,
                2 * top_k,
            )
            final_active_profiles = [
                profile_id
                for bucket in temp_buckets
                for profile_id in bucket
            ]
            break
        for index in range(advancing_bucket_count):
            buckets[index] = temp_buckets[index]
            random.shuffle(buckets[index])

    logger.info(
        "Swiss tournament completed. Executing final ranking on %d survivors.",
        len(final_active_profiles),
    )
    final_profiles = {
        profile_id: all_profiles[profile_id]
        for profile_id in final_active_profiles
    }
    final_sorted_ids = await rank_chunk(objective, final_profiles)
    results = [
        {
            "id": profile_id,
            "text": all_profiles[profile_id],
            "rank": index + 1,
        }
        for index, profile_id in enumerate(final_sorted_ids[:top_k])
    ]
    return results, len(results)
