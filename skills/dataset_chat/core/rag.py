from skills.llm_chat.llm_chat import llm_chat
from skills.config_load.config_load import config_load
from lib.logger import get_logger

logger = get_logger(__name__)

async def generate_multi_queries(question: str) -> list:
    config = config_load()
    base_prompt = config['dataset_chat']['multi_query_prompt']
    prompt = base_prompt.replace("{{question}}", question)
    
    logger.info("Generating multi-queries via LLM...")
    response = await llm_chat(prompt=prompt)
    if response:
        return [q.strip() for q in response.split('\n') if q.strip()][:3]
    return []
