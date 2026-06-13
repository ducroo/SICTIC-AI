from typing import Optional
from lib.env import get_env_var
from skills.llm_chat.llm_chat import llm_chat
from skills.config_load.config_load import config_load
from skills.dataset_chat.dataset_search import dataset_search
from lib.logger import get_logger

logger = get_logger(__name__)


def _fallback_trigger() -> str:
    try:
        config = config_load()
        return config['dataset_chat']['fallback_trigger'].replace('\\_', '_')
    except KeyError:
        return 'INSUFFICIENT_CONTEXT'


def _context_budget_chars() -> int:
    try:
        max_ctx = int(get_env_var("OLLAMA_CONTEXT_LENGTH_MAX"))
    except Exception:
        max_ctx = 8192
    return max(6_000, int(max_ctx * 3 * 0.72))


async def dataset_chat(
    dataset_name: str,
    questions: str | list[str],
    llm_instructions: Optional[str] = None,
    max_chunks: int = 25,
    strict_insufficient_context: bool = True,
) -> Optional[str]:
    """Chat with a dataset via RAG and return the string response."""

    if isinstance(questions, str):
        query_text = questions.strip()
    else:
        questions = [question.strip() for question in questions if question.strip()]
        query_text = "\n\n".join(questions)

    if not query_text:
        return None

    chunks = await dataset_search(dataset_name, questions, max_chunks=max_chunks)
    if not chunks:
        logger.warning(f"[{dataset_name}] No chunks retrieved; refusing empty-context LLM answer.")
        return _fallback_trigger()
    
    pass1_instructions = llm_instructions
    if not pass1_instructions:
        try:
            config = config_load()
            pass1_instructions = config['dataset_chat']['default_rag_instructions']
        except KeyError:
            pass1_instructions = None
            
    def build_prompt(current_chunks, inst):
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
        prompt_parts = [grounding_rule, f"Query: {query_text}"]
        if inst:
            prompt_parts.append(f"Instructions: {inst}")

        header = "\n\n".join(prompt_parts) + f"\n\nContext from {dataset_name}:\n"
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
        prompt_parts.append(f"Context from {dataset_name}:\n{context_str}")
        return "\n\n".join(prompt_parts)

    logger.info(f"[{dataset_name}] Handing off to llm_chat.")
    return await llm_chat(prompt=build_prompt(chunks, pass1_instructions))
