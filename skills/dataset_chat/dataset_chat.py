from typing import Optional
from skills.llm_chat.llm_chat import llm_chat
from skills.config_load.config_load import config_load
from skills.dataset_chat.core.rag import generate_multi_queries
from skills.dataset_chat.dataset_search import dataset_search
from lib.logger import get_logger

logger = get_logger(__name__)

async def dataset_chat(
    dataset_name: str,
    questions: str,
    llm_instructions: Optional[str] = None,
    max_chunks: int = 25
) -> Optional[str]:
    """Chat with a dataset via RAG and return the string response."""

    # 1. Parse explicit multi-queries
    if not questions.strip():
        return None
        
    is_explicit_multi = False

    # 2. Retrieve context & Pass 1
    chunks = await dataset_search(dataset_name, questions, max_chunks=max_chunks)
    
    pass1_instructions = llm_instructions
    if not pass1_instructions:
        try:
            config = config_load()
            pass1_instructions = config['dataset_chat']['default_rag_instructions']
        except KeyError:
            pass1_instructions = None
            
    def build_prompt(current_chunks, inst):
        current_chunks_copy = current_chunks.copy()
        current_chunks_copy.reverse()
        context_str = "\n\n---\n\n".join(c.to_md() for c in current_chunks_copy)
        
        prompt_parts = [f"Context from {dataset_name}:\n{context_str}", f"Query: {questions}"]
        if inst:
            prompt_parts.append(f"Instructions: {inst}")
        return "\n\n".join(prompt_parts)

    logger.info(f"[{dataset_name}] Handing off to llm_chat (Pass 1).")
    response = await llm_chat(prompt=build_prompt(chunks, pass1_instructions))
    
    # 3. Fallback (Only if single query & failed)
    try:
        config = config_load()
        fallback_trigger = config['dataset_chat']['fallback_trigger'].replace('\\_', '_')
    except KeyError:
        fallback_trigger = 'INSUFFICIENT_CONTEXT'

    if not is_explicit_multi and not llm_instructions and response and fallback_trigger in response.strip():
        logger.info(f"[{dataset_name}] Standard search failed. Generating multi-queries and retrying...")
        new_queries = generate_multi_queries(questions)
        
        combined_queries = [questions] + new_queries
        merged_chunks = await dataset_search(dataset_name, combined_queries, max_chunks=max_chunks)
        
        logger.info(f"[{dataset_name}] Handing off to llm_chat (Pass 2).")
        return await llm_chat(prompt=build_prompt(merged_chunks, None))
        
    return response
