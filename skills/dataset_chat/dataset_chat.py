"""Generate grounded Markdown or JSON from an indexed dataset."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from lib.datasets.search import dataset_search
from lib.infrastructure.ai_text_generation import (
    Review,
    generate_json,
    generate_markdown,
)
from lib.infrastructure.configuration import (
    get_env_var,
    load_repository_config,
)
from lib.infrastructure.logging import get_logger
from lib.insights import INSUFFICIENT_CONTEXT


logger = get_logger(__name__)


def _fallback_trigger() -> str:
    try:
        config = load_repository_config("dataset_chat")
        return config["fallback_trigger"].replace("\\_", "_")
    except KeyError:
        return INSUFFICIENT_CONTEXT


def _context_budget_chars() -> int:
    try:
        max_ctx = int(get_env_var("OLLAMA_CONTEXT_LENGTH_MAX"))
    except Exception:
        max_ctx = 8192
    return max(6_000, int(max_ctx * 3 * 0.72))


async def dataset_chat(
    dataset_name: str,
    queries: str | list[str],
    prompt: str,
    max_chunks: int = 25,
    strict_insufficient_context: bool = True,
    cacheable_prompt_prefix: str | None = None,
) -> str | None:
    """Generate Markdown grounded in one retrieval from a dataset."""
    prepared = await _prepare_generation(
        dataset_name,
        queries,
        prompt,
        max_chunks=max_chunks,
        strict_insufficient_context=strict_insufficient_context,
        cacheable_prompt_prefix=cacheable_prompt_prefix,
    )
    if prepared is None:
        return _fallback_trigger()
    stable_prefix, dynamic_prompt = prepared
    return await generate_markdown(
        dynamic_prompt,
        cacheable_prompt_prefix=stable_prefix,
    )


async def dataset_chat_json(
    dataset_name: str,
    queries: str | list[str],
    prompt: str,
    schema: dict[str, Any],
    reviewer: Callable[[dict | list], Review[dict | list]] | None = None,
    *,
    max_chunks: int = 25,
    cacheable_prompt_prefix: str | None = None,
) -> dict | list | None:
    """Generate schema-conformant JSON grounded in one dataset retrieval."""
    prepared = await _prepare_generation(
        dataset_name,
        queries,
        prompt,
        max_chunks=max_chunks,
        strict_insufficient_context=False,
        cacheable_prompt_prefix=cacheable_prompt_prefix,
    )
    if prepared is None:
        return None
    stable_prefix, dynamic_prompt = prepared
    return await generate_json(
        dynamic_prompt,
        schema,
        reviewer,
        cacheable_prompt_prefix=stable_prefix,
    )


async def _prepare_generation(
    dataset_name: str,
    queries: str | list[str],
    prompt: str,
    *,
    max_chunks: int,
    strict_insufficient_context: bool,
    cacheable_prompt_prefix: str | None,
) -> tuple[str | None, str] | None:
    search_queries = _search_queries(queries)
    prompt = prompt.strip()
    stable_input = (
        cacheable_prompt_prefix.strip()
        if cacheable_prompt_prefix and cacheable_prompt_prefix.strip()
        else None
    )
    if not search_queries or not prompt:
        return None

    chunks = await dataset_search(
        dataset_name,
        search_queries,
        max_chunks=max_chunks,
        raise_on_error=True,
    )
    if not chunks:
        logger.warning(
            "[%s] No chunks retrieved; refusing empty-context AI answer",
            dataset_name,
        )
        return None

    grounding_rule = _grounding_rule(strict_insufficient_context)
    stable_parts = [grounding_rule]
    if stable_input:
        stable_parts.append(stable_input)
    stable_prefix = "\n\n".join(stable_parts) + "\n\n"
    dynamic_header = f"{prompt}\n\nContext from {dataset_name}:\n"
    header = stable_prefix + dynamic_header
    context_budget = max(1_000, _context_budget_chars() - len(header))

    selected: list[str] = []
    used_characters = 0
    for chunk in chunks:
        chunk_markdown = chunk.to_md()
        separator = "\n\n---\n\n" if selected else ""
        next_size = len(separator) + len(chunk_markdown)
        if selected and used_characters + next_size > context_budget:
            break
        if not selected and next_size > context_budget:
            chunk_markdown = chunk_markdown[:context_budget].rstrip()
            next_size = len(chunk_markdown)
        selected.append(chunk_markdown)
        used_characters += next_size

    context = "\n\n---\n\n".join(selected)
    logger.info(
        "[%s] Using %s of %s chunks (%s characters)",
        dataset_name,
        len(selected),
        len(chunks),
        used_characters,
    )
    dynamic_prompt = dynamic_header + context
    if stable_input:
        return stable_prefix, dynamic_prompt
    return None, stable_prefix + dynamic_prompt


def _search_queries(queries: str | list[str]) -> str | list[str]:
    if isinstance(queries, str):
        return queries.strip()
    return [query.strip() for query in queries if query.strip()]


def _grounding_rule(strict: bool) -> str:
    if strict:
        return (
            "Use ONLY the context below. If the context does not support "
            f"the answer, output exactly: {_fallback_trigger()}"
        )
    return (
        "Use ONLY the context below. If the context has no direct evidence "
        "for a requested category, say that no evidence was found in the "
        "provided context for that category. Do not invent facts."
    )
