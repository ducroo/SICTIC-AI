from typing import Dict, Any, List
from pydantic import BaseModel

from skills.llm_chat.llm_chat import llm_chat
from skills.config_load.config_load import config_load
from lib.json_parser import repair_json_payload
from lib.logger import get_logger

logger = get_logger(__name__)

class ProfileRationale(BaseModel):
    id: str
    rationale: str

class BatchRationaleResult(BaseModel):
    results: List[ProfileRationale]

async def ranking_rationale(
    ranked_items: List[Dict[str, Any]], 
    objective: str
) -> List[Dict[str, Any]]:
    """
    Augments ranked_items with concise ranking rationales.
    Person identity fields are supplied by the Person metadata, not by the LLM.
    """
    if not ranked_items:
        return []

    config = config_load()
    prompt = config['ranking_rationale']['rationale_instructions']

    profiles_text = []
    # ranked_items comes strictly ordered with final ranks already populated.
    for item in ranked_items:
        item_id = item["id"]
        content = item.get("text", "Content missing.")
        profiles_text.append(f"### Rank {item['rank']} | Profile ID: {item_id}\n\n{content}")
        
    prompt = prompt.replace("{{objective}}", objective)
    prompt = prompt.replace("{{profiles_text}}", "\n\n---\n\n".join(profiles_text))
    
    try:
        response_content = await llm_chat(prompt, response_format=BatchRationaleResult)
        if not response_content:
            return ranked_items

        parsed_dict = repair_json_payload(response_content)
        parsed_data = BatchRationaleResult.model_validate(parsed_dict)

        rationale_lookup = {r.id: r.rationale for r in parsed_data.results}

        # Merge the results back into the original ranked_items list
        for item in ranked_items:
            item_id = item["id"]
            if item_id in rationale_lookup:
                item["rationale"] = rationale_lookup[item_id]
            else:
                item["rationale"] = "Rationale missing from LLM response."

    except Exception as e:
        logger.error(f"Error in ranking_rationale: {e}")
        # Ensure we always return the original structure even if the LLM call fails
        for item in ranked_items:
            item["rationale"] = "Error generating rationale."

    return ranked_items
