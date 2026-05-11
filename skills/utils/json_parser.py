import json
from skills.utils.logger import get_logger

logger = get_logger(__name__)

import re

def repair_json_payload(raw_output: str) -> dict | list:
    """Extracts and parses JSON from a raw LLM string."""
    if not raw_output:
        raise ValueError("Empty response from LLM.")
        
    # 1. Try to find a markdown JSON block first
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw_output)
    if match:
        json_str = match.group(1).strip()
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass # Fallback to manual extraction

    try:
        # Find first { or [
        start_brace = raw_output.find('{')
        start_bracket = raw_output.find('[')
        
        start_idx = -1
        end_idx = -1
        if start_brace != -1 and (start_bracket == -1 or start_brace < start_bracket):
            start_idx = start_brace
            end_idx = raw_output.rfind('}')
        elif start_bracket != -1:
            start_idx = start_bracket
            end_idx = raw_output.rfind(']')
            
        if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
            json_str = raw_output[start_idx:end_idx+1]
            return json.loads(json_str)
        else:
            logger.warning("No JSON object found in LLM response.")
            raise ValueError("Failed to parse LLM response: No JSON object found.")
    except json.JSONDecodeError as e:
        logger.warning(f"JSON decode error: {e}")
        raise ValueError(f"Failed to parse LLM response: JSON decode error {e}")
