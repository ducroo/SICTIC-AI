import json
import re

from lib.logger import get_logger

logger = get_logger(__name__)


_VALID_JSON_ESCAPES = {'"', "\\", "/", "b", "f", "n", "r", "t"}


def _escape_invalid_json_backslashes(json_str: str) -> str:
    """Escape bare backslashes inside JSON strings without changing valid escapes."""
    repaired = []
    in_string = False
    escaped = False
    i = 0

    while i < len(json_str):
        char = json_str[i]
        if not in_string:
            repaired.append(char)
            if char == '"':
                in_string = True
            i += 1
            continue

        if escaped:
            if char in _VALID_JSON_ESCAPES:
                repaired.append(char)
                escaped = False
                i += 1
                continue
            if char == "u" and re.fullmatch(
                r"[0-9a-fA-F]{4}", json_str[i + 1 : i + 5]
            ):
                repaired.append(char)
                escaped = False
                i += 1
                continue
            repaired.append("\\")
            repaired.append(char)
            escaped = False
            i += 1
            continue

        if char == "\\":
            repaired.append(char)
            escaped = True
            i += 1
            continue
        if char == '"':
            in_string = False
        repaired.append(char)
        i += 1

    if escaped:
        repaired.append("\\")
    return "".join(repaired)


def _loads_with_llm_repairs(json_str: str) -> dict | list:
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as first_error:
        repaired = _escape_invalid_json_backslashes(json_str)
        if repaired == json_str:
            raise first_error
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            raise first_error

def repair_json_payload(raw_output: str) -> dict | list:
    """Extracts and parses JSON from a raw LLM string."""
    if not raw_output:
        raise ValueError("Empty response from LLM.")
        
    # 1. Try to find a markdown JSON block first
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw_output)
    if match:
        json_str = match.group(1).strip()
        try:
            return _loads_with_llm_repairs(json_str)
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
            return _loads_with_llm_repairs(json_str)
        else:
            logger.warning("No JSON object found in LLM response.")
            raise ValueError("Failed to parse LLM response: No JSON object found.")
    except json.JSONDecodeError as e:
        logger.warning(f"JSON decode error: {e}")
        raise ValueError(f"Failed to parse LLM response: JSON decode error {e}")
