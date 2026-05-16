import os
import asyncio
from typing import Dict, Any, List, Tuple
from skills.llm_chat.llm_chat import llm_chat
from skills.config_load.config_load import config_load
from lib.logger import get_logger

logger = get_logger(__name__)

async def ranking_writeup(
    ranked_items: List[Dict[str, Any]], 
    objective: str, 
    top_k: int
) -> str:
    """
    Generic utility to generate a rationale report for tournament winners.
    Assumes ranked_items contains 'id', 'rank', and 'text' keys.
    """

    config=config_load()
    prompt = config['ranking_writeup']['writeup_instructions']

    profiles_text = []
    for item in ranked_items[:top_k]:
        item_id = item["id"]
        content = item.get("text", "Content missing.")
        profiles_text.append(f"### Rank {item['rank']}: {item_id}\n\n{content}")
        
    prompt = prompt.replace("{{objective}}", objective)
    prompt = prompt.replace("{{profiles_text}}", "\n\n---\n\n".join(profiles_text))
    
    #logger.info(f"ranking_writeup prompt: \n\n {prompt}")

    return await llm_chat(prompt)
