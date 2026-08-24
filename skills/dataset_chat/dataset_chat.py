from typing import Any, Optional
from lib.env import get_env_var
from skills.llm_chat.llm_chat import llm_chat
from skills.config_load.config_load import config_load
from lib.datasets.search import dataset_search
from lib.logger import get_logger
from lib.insights import INSUFFICIENT_CONTEXT

logger = get_logger(__name__)


def _fallback_trigger() -> str:
    try:
        config = config_load()
        return config['dataset_chat']['fallback_trigger'].replace('\\_', '_')
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
    response_format: Optional[Any] = None,
    cacheable_prompt_prefix: Optional[str] = None,
) -> Optional[str]:
    """Run one RAG using search queries and an independent LLM prompt."""
    if isinstance(queries, str):
        search_queries: str | list[str] = queries.strip()
        has_queries = bool(search_queries)
    else:
        search_queries = [query.strip() for query in queries if query.strip()]
        has_queries = bool(search_queries)

    prompt = prompt.strip()
    if cacheable_prompt_prefix is not None:
        cacheable_prompt_prefix = cacheable_prompt_prefix.strip() or None
    if not has_queries or not prompt:
        return None

    chunks = await dataset_search(
        dataset_name,
        search_queries,
        max_chunks=max_chunks,
        raise_on_error=True,
    )
    if not chunks:
        logger.warning(f"[{dataset_name}] No chunks retrieved; refusing empty-context LLM answer.")
        return _fallback_trigger()
    
    def build_prompt(current_chunks):
        if strict_insufficient_context:
            grounding_rule = (
                "Use ONLY the context below. If the context does not support the answer, "
                f"output exactly: {_fallback_trigger()}"
            )
        else:
            grounding_rule = (
                "Use ONLY the context below. If the context has no direct evidence for "
                "a requested category, say that no evidence was found in the provided "
                "context for that category. Do not invent facts."
            )
        stable_parts = [grounding_rule]
        if cacheable_prompt_prefix:
            stable_parts.append(cacheable_prompt_prefix)
        stable_prefix = "\n\n".join(stable_parts) + "\n\n"
        dynamic_header = f"{prompt}\n\nContext from {dataset_name}:\n"
        header = stable_prefix + dynamic_header
        context_budget = max(1_000, _context_budget_chars() - len(header))

        selected = []
        used_chars = 0
        for chunk in current_chunks:
            chunk_md = chunk.to_md()
            separator = "\n\n---\n\n" if selected else ""
            next_size = len(separator) + len(chunk_md)
            if selected and used_chars + next_size > context_budget:
                break
            if not selected and next_size > context_budget:
                chunk_md = chunk_md[:context_budget].rstrip()
                next_size = len(chunk_md)
            selected.append(chunk_md)
            used_chars += next_size

        context_str = "\n\n---\n\n".join(selected)
        logger.info(
            f"[{dataset_name}] Using {len(selected)} of {len(current_chunks)} chunks "
            f"({used_chars} chars) for RAG prompt."
        )
        dynamic_prompt = dynamic_header + context_str
        if cacheable_prompt_prefix:
            return stable_prefix, dynamic_prompt
        return None, stable_prefix + dynamic_prompt

    logger.info(f"[{dataset_name}] Handing off to llm_chat.")
    stable_prefix, dynamic_prompt = build_prompt(chunks)
    return await llm_chat(
        prompt=dynamic_prompt,
        response_format=response_format,
        cacheable_prompt_prefix=stable_prefix,
    )
