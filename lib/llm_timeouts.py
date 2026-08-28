"""Shared LLM HTTP timeout defaults.

Structured JSON calls must fail fast. Unbounded thinking plus a one-hour
retry loop is how a single due-diligence check stalls for hours.
"""

from __future__ import annotations

import os

from lib.logger import get_logger

logger = get_logger(__name__)

DEFAULT_LLM_REQUEST_TIMEOUT = 3600.0
DEFAULT_STRUCTURED_REQUEST_TIMEOUT = 180.0
DEFAULT_STRUCTURED_NUM_PREDICT = 4096


def float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Ignoring non-numeric %s=%r", name, raw)
        return default


def int_env(name: str, default: int) -> int:
    return int(float_env(name, float(default)))


def llm_request_timeout() -> float:
    return float_env("LLM_REQUEST_TIMEOUT", DEFAULT_LLM_REQUEST_TIMEOUT)


def structured_request_timeout() -> float:
    return float_env(
        "LLM_STRUCTURED_REQUEST_TIMEOUT",
        DEFAULT_STRUCTURED_REQUEST_TIMEOUT,
    )


def structured_num_predict() -> int:
    return max(
        1,
        int_env("LLM_STRUCTURED_NUM_PREDICT", DEFAULT_STRUCTURED_NUM_PREDICT),
    )


def effective_request_timeout(
    *,
    structured: bool,
    override: float | None = None,
) -> float:
    if override is not None:
        return override
    if structured:
        return structured_request_timeout()
    return llm_request_timeout()


def lease_floor_seconds() -> float:
    """Gateway leases must outlive the longest in-flight LLM HTTP call."""
    return max(llm_request_timeout(), structured_request_timeout())
