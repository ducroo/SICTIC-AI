from typing import List
from skills.startup_profile.startup_profile import startup_profile
from skills.llm_chat.llm_chat import llm_chat
from lib.json_parser import repair_json_payload
from lib.logger import get_logger

logger = get_logger(__name__)

async def compile_startup_profiles(startups: List[str]) -> str:
    startup_profiles_text = []
    logger.info("Profiling startups for new evaluations...")
    for startup in startups:
        try:
            profile_out, _ = await startup_profile(startup)
            startup_profiles_text.append(f"STARTUP: {startup}\n{profile_out}\n")
        except Exception as e:
            logger.error(f"Failed to profile startup {startup}: {e}")
            
    return "\n".join(startup_profiles_text)

async def process_single_investor(investor: str, investor_data_str: str, compiled_startups: str, prompt_template: str, max_startups: int = 5) -> List[str]:
    full_prompt = prompt_template.replace("{{investor_profile}}", f"=== INVESTOR PROFILE: {investor} ===\n{investor_data_str}").replace("{{startup_profiles}}", compiled_startups)
    
    logger.info(f"Ranking startups for {investor}...")
    raw_response = await llm_chat(prompt=full_prompt)
    
    parsed = repair_json_payload(raw_response if raw_response else "")
    rankings = []
    if isinstance(parsed, list):
        rankings = parsed
    elif isinstance(parsed, dict):
        for k, v in parsed.items():
            if isinstance(v, list):
                rankings = v
                break
    if not rankings and "startup_name" in parsed:
            rankings = [parsed]
            
    # Sort by rank and truncate
    def get_rank(item):
        try:
            return int(item.get('rank', 999))
        except (ValueError, TypeError):
            return 999
            
    rankings.sort(key=get_rank)
    rankings = rankings[:max_startups]

    new_lines = []
    for rank_item in rankings:
        try:
            s_name = rank_item.get('startup_name', 'Unknown')
            rationale = rank_item.get('rationale', '')
            
            rationale = str(rationale).replace("\n", " ")
            
            line = f"| {s_name} | {rationale} |"
            new_lines.append(line)
        except Exception as e:
            logger.warning(f"Failed to parse ranking item for {investor}: {e}")
            
    return new_lines
