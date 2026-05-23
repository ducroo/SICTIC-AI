import re
from typing import List, Dict
from lib.logger import get_logger
from lib.storage import get_storage
from skills.config_load.config_load import config_load
from skills.llm_chat.llm_chat import llm_chat
from lib.json_parser import repair_json_payload

logger = get_logger(__name__)

def _get_person_profile_content(inv_name: str) -> str | None:
    storage = get_storage()
    sanitized_name = re.sub(r'[^\w]+', '_', inv_name.strip()).strip('_').lower()
    pp_dir = "insights/sictic_members/person_profile"
    if storage.exists(pp_dir):
        for f in storage.list(pp_dir, suffix=".md"):
            if f.startswith(sanitized_name):
                return storage.read_text(f"{pp_dir}/{f}")
    return None

async def rank_investors(filtered_investors: List[str], profile_content: str, max_investors: int, default_llm: str) -> List[Dict]:
    try:
        conf = config_load()
        if "ollama" in default_llm.lower() or "local" in default_llm.lower():
            strategy = "local"
            llm_instructions = conf.get('potential_investors', {}).get('llm_instructions_local', "Rate 0-100 and give rationale in JSON.")
        else:
            strategy = "cloud"
            llm_instructions = conf.get('potential_investors', {}).get('llm_instructions_cloud', "Rank in JSON.")
    except KeyError as e:
        logger.warning(f"Missing config for potential_investors: {e}. Using defaults.")
        strategy = "local" if "ollama" in default_llm.lower() else "cloud"
        llm_instructions = "Rate 0-100 and give rationale in JSON."

    ranked_results = []
    
    if strategy == "local":
        logger.info("Using Strategy A: Local Model Iterative Scoring")
        for inv in filtered_investors:
            pp_content = _get_person_profile_content(inv)
            if not pp_content:
                continue
                
            prompt = f"Startup Profile:\n{profile_content}\n\nInvestor Profile (Name: {inv}):\n{pp_content}\n\nInstructions:\n{llm_instructions}"
            response = await llm_chat(prompt=prompt)
            
            if not response or not response.strip():
                logger.error(f"LLM returned empty response for {inv}. Skipping.")
                continue
                
            try:
                data = repair_json_payload(response)
                if isinstance(data, dict):
                    score = int(data.get("score", 0))
                    rationale = data.get("rationale", "")
                    ranked_results.append({"investor_name": inv, "score": score, "rationale": rationale})
                else:
                    raise ValueError("Expected dictionary from repair_json_payload.")
            except Exception as e:
                logger.error(f"Failed to parse JSON for {inv}: {e}. Response was: {response}")
                raise ValueError(f"LLM returned invalid JSON for {inv}")
                
        ranked_results.sort(key=lambda x: x["score"], reverse=True)
        
    else:
        logger.info("Using Strategy B: Cloud Model Monolithic Ranking")
        all_profiles = []
        for inv in filtered_investors:
            pp_content = _get_person_profile_content(inv)
            if pp_content:
                all_profiles.append(f"--- Investor Profile: {inv} ---\n{pp_content}")
                
        profiles_str = "\n\n".join(all_profiles)
        prompt = f"Startup Profile:\n{profile_content}\n\nInvestor Profiles to Rank:\n{profiles_str}\n\nInstructions:\n{llm_instructions}"
        
        response = await llm_chat(prompt=prompt)
        
        if not response or not response.strip():
            raise ValueError("Cloud LLM returned empty response.")
            
        try:
            data = repair_json_payload(response)
            items = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, list):
                        items = v
                        break
                        
            for item in items:
                ranked_results.append({
                    "investor_name": item.get("investor_name", "Unknown"),
                    "score": int(item.get("rank", 0)),
                    "rationale": item.get("rationale", "")
                })
        except Exception as e:
            logger.error(f"Failed to parse Cloud JSON ranking: {e}")
            raise ValueError(f"Cloud LLM returned invalid JSON: {e}")
            
        ranked_results.sort(key=lambda x: x["score"])

    return ranked_results[:max_investors]
