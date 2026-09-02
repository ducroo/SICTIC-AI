"""Generate provider-neutral Markdown and schema-conformant JSON."""

from lib.infrastructure.ai_text_generation.generation import (
    generate_json,
    generate_markdown,
)
from lib.infrastructure.ai_text_generation.types import Review

__all__ = ["Review", "generate_json", "generate_markdown"]
