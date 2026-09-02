from __future__ import annotations

import re
from typing import Literal

from lib.infrastructure.configuration import get_env_var
from lib.insights.manifest import config_hash
from lib.insights.paths import model_slug
from lib.infrastructure.logging import get_logger

logger = get_logger(__name__)

InsightSelection = Literal["any", "reusable"]


def _stored_config_hash(entry: dict) -> str | None:
    """Read current manifests while retaining legacy manifest compatibility."""
    return entry.get("config_sha256") or entry.get("prompt_sha256")


def ranked_models() -> list[tuple[str, str]]:
    return [
        (model.strip(), model_slug(model.strip()))
        for model in get_env_var("RANKED_LLMS").split(",")
        if model.strip()
    ]


def find(insight, *, selection: InsightSelection):
    if selection == "any":
        return _find_any(insight)
    if selection == "reusable":
        return _find_reusable(insight)
    raise ValueError(f"Unsupported insight selection: {selection!r}")


def _find_reusable(insight):
    manual = insight._candidate("manual")
    if manual.exists():
        logger.info("Using manual insight: %s", manual.path)
        return manual

    manifest = insight._load_manifest()
    expected_revisions = insight._dataset_revisions()
    if expected_revisions is None:
        return None
    expected_config_hash = config_hash(insight.config_key)

    for model, ranked_model_slug in ranked_models():
        candidate = insight._candidate(model)
        if not candidate.exists():
            continue
        entry = manifest["entries"].get(candidate.path)
        if (
            isinstance(entry, dict)
            and entry.get("model") == ranked_model_slug
            and entry.get("dataset_revisions") == expected_revisions
            and _stored_config_hash(entry) == expected_config_hash
        ):
            logger.info("Using reusable insight: %s", candidate.path)
            return candidate
    return None


def is_reusable(insight) -> bool:
    """Return whether this exact model/path is fresh for its config and data."""
    if not insight.exists():
        return False
    manifest = insight._load_manifest()
    expected_revisions = insight._dataset_revisions()
    if expected_revisions is None:
        return False
    entry = manifest["entries"].get(insight.path)
    return bool(
        isinstance(entry, dict)
        and entry.get("model") == model_slug(insight.model)
        and entry.get("dataset_revisions") == expected_revisions
        and _stored_config_hash(entry) == config_hash(insight.config_key)
    )


def _find_any(insight):
    from lib.storage import get_storage

    suffix = f".{insight.extension}"
    available = set(get_storage().list(insight.directory, suffix=suffix))
    manual = insight._candidate("manual")
    if manual.filename in available:
        return manual

    seen = {manual.filename}
    for model, _ranked_model_slug in ranked_models():
        candidate = insight._candidate(model)
        seen.add(candidate.filename)
        if candidate.filename in available:
            return candidate

    prefix = f"{insight._base_name}-"
    remaining = [
        filename
        for filename in available - seen
        if filename.startswith(prefix) and filename.endswith(suffix)
    ]
    if not remaining:
        return None
    remaining.sort(key=fallback_sort_key, reverse=True)
    return insight._candidate_from_filename(remaining[0])


def fallback_sort_key(filename: str) -> tuple[int, str]:
    digits = [int(value) for value in re.findall(r"\d+", filename)]
    return (max(digits) if digits else 0, filename)
