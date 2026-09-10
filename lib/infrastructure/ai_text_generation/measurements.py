"""Append privacy-safe AI generation measurements as JSON Lines."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from numbers import Real
from threading import Lock
from typing import Any

from lib.infrastructure.logging import LOG_DIR, get_logger


logger = get_logger(__name__)

MEASUREMENT_FILE = LOG_DIR / "ai-text-generation.jsonl"
_WRITE_LOCK = Lock()
_LOCAL_DESCRIPTOR_PREFIXES = ("ollama/", "mlx/", "infinity/")
_OLLAMA_DURATION_FIELDS = (
    "load_duration",
    "prompt_eval_duration",
    "eval_duration",
    "total_duration",
)


def measurements_enabled() -> bool:
    """Return whether operational measurement records should be written."""
    return os.environ.get("SICTIC_TESTING") != "1"


def active_local_jobs(snapshot: dict[str, Any]) -> int:
    """Count active scheduler leases competing for local compute."""
    leases = snapshot.get("leases", {})
    count = len(leases.get("docling", []))
    for lease in leases.get("model", []):
        descriptor = str(lease.get("descriptor") or "")
        if descriptor in {"docling", "infinity"} or descriptor.startswith(
            _LOCAL_DESCRIPTOR_PREFIXES
        ):
            count += 1
    return count


def record_attempt(
    *,
    request_id: str,
    model: str,
    output_type: str,
    attempt: int,
    input_characters: int,
    output_characters: int,
    reasoning_characters: int | None,
    context_size: int | None,
    thinking_enabled: bool | None,
    timeout_seconds: float,
    concurrent_local_jobs: int | None,
    scheduler_wait_seconds: float | None,
    provider_duration_seconds: float | None,
    total_duration_seconds: float,
    status: str,
    error_kind: str | None,
    response: Any = None,
) -> None:
    """Write one model-attempt record without prompt or response content."""
    if not measurements_enabled():
        return
    record: dict[str, Any] = {
        "schema_version": 2,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id,
        "model": model,
        "output_type": output_type,
        "attempt": attempt,
        "input_characters": input_characters,
        "output_characters": output_characters,
        "reasoning_characters": reasoning_characters,
        "context_size": context_size,
        "thinking_enabled": thinking_enabled,
        "timeout_seconds": timeout_seconds,
        "concurrent_local_jobs": concurrent_local_jobs,
        "scheduler_wait_seconds": scheduler_wait_seconds,
        "provider_duration_seconds": provider_duration_seconds,
        "total_duration_seconds": total_duration_seconds,
        "provider_status": status,
        "error_kind": error_kind,
        **_response_metrics(response),
    }
    encoded = (
        json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    try:
        MEASUREMENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _WRITE_LOCK:
            descriptor = os.open(
                MEASUREMENT_FILE,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                0o600,
            )
            try:
                os.write(descriptor, encoded)
            finally:
                os.close(descriptor)
    except OSError as error:
        logger.warning(
            "Could not write AI text-generation measurement to %s: %s",
            MEASUREMENT_FILE,
            error,
        )


def _response_metrics(response: Any) -> dict[str, Any]:
    usage = _mapping(getattr(response, "usage", None))
    prompt_details = _mapping(usage.get("prompt_tokens_details"))
    completion_details = _mapping(usage.get("completion_tokens_details"))
    result: dict[str, Any] = {
        "prompt_tokens": _integer(usage.get("prompt_tokens")),
        "completion_tokens": _integer(usage.get("completion_tokens")),
        "cached_prompt_tokens": _integer(
            prompt_details.get("cached_tokens")
        ),
        "reasoning_tokens": _integer(
            completion_details.get("reasoning_tokens")
        ),
        "finish_reason": _finish_reason(response),
    }
    for field in _OLLAMA_DURATION_FIELDS:
        result[f"{field}_ns"] = _find_number(response, field)
    return result


def _finish_reason(response: Any) -> str | None:
    try:
        value = response.choices[0].finish_reason
    except (AttributeError, IndexError, KeyError, TypeError):
        return None
    return str(value) if value is not None else None


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return {
        key: item
        for key, item in vars(value).items()
        if not key.startswith("_")
    } if hasattr(value, "__dict__") else {}


def _find_number(value: Any, key: str, depth: int = 0) -> int | float | None:
    if depth > 3:
        return None
    mapping = _mapping(value)
    candidate = mapping.get(key)
    if isinstance(candidate, Real) and not isinstance(candidate, bool):
        return candidate
    for child_key in (
        "_hidden_params",
        "provider_specific_fields",
        "additional_headers",
    ):
        found = _find_number(mapping.get(child_key), key, depth + 1)
        if found is not None:
            return found
    hidden = getattr(value, "_hidden_params", None)
    if hidden is not None and hidden is not value:
        return _find_number(hidden, key, depth + 1)
    return None


def _integer(value: Any) -> int | None:
    return int(value) if isinstance(value, Real) else None
