"""Operation-specific metadata extraction for the shared scheduler."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class JobProfile:
    """Non-sensitive metadata used to schedule one operation."""

    kind: str
    descriptor: str
    input_size: int
    cached_input_size: int = 0
    affinity_key: str | None = None
    parameters: dict[str, object] = field(default_factory=dict)


OperationInspector = Callable[[Mapping[str, Any]], JobProfile]

_inspectors: dict[Callable[..., Any], OperationInspector] = {}


def register_operation(
    operation: Callable[..., Any],
    inspector: OperationInspector,
) -> None:
    """Register how scheduling metadata is derived for an operation."""
    if not callable(operation) or not callable(inspector):
        raise TypeError("operation and inspector must be callable")
    existing = _inspectors.get(operation)
    if existing is not None and existing is not inspector:
        raise ValueError(f"Scheduler operation already registered: {operation!r}")
    _inspectors[operation] = inspector


def inspect_operation(
    operation: Callable[..., Any],
    operation_kwargs: Mapping[str, Any],
) -> JobProfile:
    """Derive and validate scheduling metadata for a registered operation."""
    inspector = _inspectors.get(operation)
    if inspector is None:
        raise ValueError(f"Unregistered scheduler operation: {operation!r}")
    if not all(isinstance(key, str) for key in operation_kwargs):
        raise TypeError("Scheduler operation argument names must be strings")
    profile = inspector(operation_kwargs)
    if not isinstance(profile, JobProfile):
        raise TypeError("Scheduler operation inspector must return JobProfile")
    if not profile.kind.strip():
        raise ValueError("Scheduler job kind cannot be empty")
    if not profile.descriptor.strip():
        raise ValueError("Scheduler job descriptor cannot be empty")
    if profile.input_size < 0:
        raise ValueError("Scheduler job input_size cannot be negative")
    if not 0 <= profile.cached_input_size <= profile.input_size:
        raise ValueError(
            "Scheduler cached_input_size must be between zero and input_size"
        )
    if profile.affinity_key is not None and not profile.affinity_key.strip():
        raise ValueError("Scheduler affinity_key cannot be empty")
    if not isinstance(profile.parameters, dict):
        raise TypeError("Scheduler job parameters must be a dictionary")
    try:
        json.dumps(profile.parameters)
    except (TypeError, ValueError) as error:
        raise TypeError(
            "Scheduler job parameters must be JSON serializable"
        ) from error
    return profile
