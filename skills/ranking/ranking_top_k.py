import asyncio
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

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

DEFAULT_BATCH_SIZE = 16
_RANKING_ATTEMPTS = 3


@dataclass(frozen=True)
class RankingInspection:
    ranked_ids: list[str]
    duplicates: list[str]
    missing: list[str]
    repaired_ids: list[str]

    @property
    def valid(self) -> bool:
        return not self.duplicates and not self.missing


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


def _inspect_ranked_ids(
    ranked_ids: list[str],
    expected_ids: list[str],
) -> RankingInspection:
    expected = set(expected_ids)
    unexpected = [item for item in ranked_ids if item not in expected]
    if unexpected:
        raise ValueError(
            "Top-k ranking IDs do not match the candidates; "
            f"unexpected={unexpected}."
        )

    seen: set[str] = set()
    duplicates: list[str] = []
    repaired: list[str] = []
    for profile_id in ranked_ids:
        if profile_id in seen:
            if profile_id not in duplicates:
                duplicates.append(profile_id)
            continue
        seen.add(profile_id)
        repaired.append(profile_id)
    missing = [profile_id for profile_id in expected_ids if profile_id not in seen]
    repaired.extend(missing)
    return RankingInspection(
        ranked_ids=list(ranked_ids),
        duplicates=duplicates,
        missing=missing,
        repaired_ids=repaired,
    )


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
    )
    prompt += (
        "\n\nReturn every supplied profile ID exactly once; "
        "do not repeat or omit IDs."
    )
    prompt += "\n\n" + schema_prompt_block(response_schema)

    attempt_errors: list[str] = []
    retry_feedback = ""
    repairable_inspection: RankingInspection | None = None

    for attempt in range(1, _RANKING_ATTEMPTS + 1):
        repairable_inspection = None
        final_prompt = prompt + retry_feedback

        try:
            response_content = await llm_chat(
                final_prompt,
                response_format=json_schema_response_format(
                    "ranked_profile_ids",
                    response_schema,
                ),
            )
            if not response_content:
                raise ValueError("Ranking model returned no content.")

            parsed = repair_json_payload(response_content)
            validate_json_schema(
                parsed,
                response_schema,
                label="Top-k ranking response",
            )
            inspection = _inspect_ranked_ids(
                parsed["ranked_profiles_ids"],
                profile_ids,
            )
            if not inspection.valid:
                repairable_inspection = inspection
                raise ValueError(
                    "Top-k ranking must contain every candidate ID exactly "
                    f"once; duplicates={inspection.duplicates}, "
                    f"missing={inspection.missing}."
                )
        except Exception as error:
            if not is_retryable_structured_error(error):
                raise
            attempt_errors.append(str(error))
            logger.warning(
                "Ranking model returned an invalid response on attempt "
                "%s/%s: %s",
                attempt,
                _RANKING_ATTEMPTS,
                error,
            )
            if attempt < _RANKING_ATTEMPTS:
                retry_feedback = structured_correction_feedback(error)
            continue

        return inspection.ranked_ids

    if repairable_inspection is None:
        raise RuntimeError(
            "Top-k ranking failed after "
            f"{_RANKING_ATTEMPTS} attempts: "
            + " | ".join(attempt_errors)
        )

    repaired_inspection = _inspect_ranked_ids(
        repairable_inspection.repaired_ids,
        profile_ids,
    )
    if not repaired_inspection.valid:
        raise ValueError(
            "Could not repair top-k ranking into a complete permutation."
        )

    logger.warning(
        "Repaired duplicate ranking after %s attempts; duplicates=%s, "
        "restored_missing=%s.",
        _RANKING_ATTEMPTS,
        repairable_inspection.duplicates,
        repairable_inspection.missing,
    )
    return repaired_inspection.ranked_ids


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
