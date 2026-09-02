"""Public value types for AI text generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class Review(Generic[T]):
    """A potentially corrected output and its remaining business problems."""

    output: T
    problems: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return not self.problems
