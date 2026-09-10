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
    context = f"{insight.dataset}/{insight.skill}"
    manual = insight._candidate("manual")
    if manual.exists():
        logger.info("[%s] Reusing manual version: %s", context, manual.path)
        return manual

    manifest = insight._load_manifest()
    missing_revisions: list[str] = []
    expected_revisions = insight._dataset_revisions(missing=missing_revisions)
    if expected_revisions is None:
        logger.info(
            "[%s] Cache miss: indexed revision missing: %s",
            context, ", ".join(missing_revisions),
        )
        return None
    expected_config_hash = config_hash(insight.config_key)

    found_candidate = False
    for model, ranked_model_slug in ranked_models():
        candidate = insight._candidate(model)
        if not candidate.exists():
            continue
        found_candidate = True
        entry = manifest["entries"].get(candidate.path)
        if (
            isinstance(entry, dict)
            and entry.get("model") == ranked_model_slug
            and entry.get("dataset_revisions") == expected_revisions
            and _stored_config_hash(entry) == expected_config_hash
        ):
            logger.info(
                "[%s] Reusing generated version (%s): %s",
                context, ranked_model_slug, candidate.path,
            )
            return candidate
        reasons = _rejection_reasons(entry, ranked_model_slug, expected_revisions, expected_config_hash)
        logger.info(
            "[%s] Cache miss (%s): %s [file: %s]",
            context, ranked_model_slug, "; ".join(reasons), candidate.path,
        )
    if not found_candidate:
        logger.info("[%s] Cache miss: no existing candidate files", context)
    return None


def _rejection_reasons(entry, model, revisions, configuration_hash) -> list[str]:
    """Describe a rejected candidate without logging prompt or contact content."""
    if not isinstance(entry, dict):
        return ["freshness metadata missing"]
    reasons = []
    stored_revisions = entry.get("dataset_revisions")
    stored_hash = _stored_config_hash(entry)
    if not entry.get("model") or not isinstance(stored_revisions, dict) or not stored_hash:
        reasons.append("freshness metadata missing or invalid")
    if entry.get("model") and entry["model"] != model:
        reasons.append("stored model mismatch")
    if isinstance(stored_revisions, dict):
        changed = sorted(
            name for name in set(stored_revisions) | set(revisions)
            if stored_revisions.get(name) != revisions.get(name)
        )
        if changed:
            reasons.append(f"dataset changed: {', '.join(changed)}")
    if stored_hash and stored_hash != configuration_hash:
        reasons.append("prompt/configuration/inputs changed")
    return reasons


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
