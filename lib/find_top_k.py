import asyncio
import random
from typing import Dict, List, Any, Tuple
from pydantic import BaseModel, Field

from skills.llm_chat.llm_chat import llm_chat
from skills.config_load.config_load import config_load
from lib.json_parser import repair_json_payload
from lib.logger import get_logger

logger = get_logger(__name__)

class RankedProfilesResult(BaseModel):
    ranked_profile_ids: List[str] = Field(
        description="List of profile IDs ordered from best to worst",
        alias="ranked_profiles_ids"
    )

    class Config:
        populate_by_name = True

async def rank_chunk(objective: str, profiles: Dict[str, str]) -> List[str]:
    """Ranks a small set of profiles using LLM and returns sorted profile IDs."""
    profile_ids = list(profiles.keys())
    if len(profile_ids) <= 1:
        return profile_ids
        
    config = config_load()
    prompt = config["find_top_k"]["pivot_instructions"]
        
    profiles_text = "\n\n".join([f"ID: {i}\n{profiles[i]}" for i in profile_ids])
    prompt = prompt.replace("{{profiles_text}}", profiles_text)
    prompt = prompt.replace("{{objective}}", objective)
    prompt = prompt.replace("{{n_profiles}}", str(len(profiles)))
    prompt = prompt.replace("{{IDs_profiles}}", ", ".join(profile_ids))
    
    try:
        response_content = await llm_chat(prompt, response_format=RankedProfilesResult)
        if not response_content:
            return profile_ids # fallback: original order
            
        parsed_dict = repair_json_payload(response_content)
        parsed_data = RankedProfilesResult.model_validate(parsed_dict)
        
        valid_ranked = [i for i in parsed_data.ranked_profile_ids if i in profiles]
        # Append any missing ones at the end
        for pid in profile_ids:
            if pid not in valid_ranked:
                valid_ranked.append(pid)
                
        return valid_ranked
    except Exception as e:
        logger.error(f"Error in rank_chunk: {e}")
        return profile_ids # fallback

async def find_top_k(objective: str, all_profiles: Dict[str, str], top_k: int = 8) -> Tuple[List[Dict[str, Any]], int]:
    """
    Finds the top_k profiles from all_profiles using a 4-bucket Swiss tournament.
    Returns a tuple containing:
    - A sorted list of dictionaries with keys: 'id', 'text', 'rank'.
    - The actual_top_k.
    """
    logger.info(f"Starting 4-bucket Swiss tournament find_top_k with {len(all_profiles)} candidates for top_k={top_k}.")
    
    # 1. Initialize 4 random buckets
    active_profiles = list(all_profiles.keys())
    random.shuffle(active_profiles)
    
    buckets = [[] for _ in range(4)]
    for i, pid in enumerate(active_profiles):
        buckets[i % 4].append(pid)
        
    # 2. Tournament loop
    while True:
        total_remaining = sum(len(b) for b in buckets)
        logger.info(f"Swiss iteration: {total_remaining} active profiles.")
        
        # Pull elements to form chunks of 8 (up to 2 from each bucket)
        chunks = []
        current_chunk = []
        
        # Keep drawing until all buckets are empty
        while any(len(b) > 0 for b in buckets):
            for b in buckets:
                # Take up to 2 elements from this bucket
                for _ in range(2):
                    if b:
                        current_chunk.append(b.pop(0))
                        
            # If we've gathered 8, or if we've exhausted all buckets but have a remainder chunk
            if len(current_chunk) == 8 or (not any(len(b) > 0 for b in buckets) and len(current_chunk) > 0):
                chunks.append(current_chunk)
                current_chunk = []
                
        # Rank the chunks concurrently
        tasks = []
        for chunk in chunks:
            chunk_profiles = {pid: all_profiles[pid] for pid in chunk}
            tasks.append(rank_chunk(objective, chunk_profiles))
            
        chunk_rankings = await asyncio.gather(*tasks)
        
        # Distribute into 8 temporary buckets based on rank
        temp_buckets = [[] for _ in range(8)]
        for ranked_chunk in chunk_rankings:
            n = len(ranked_chunk)
            for i, pid in enumerate(ranked_chunk):
                bucket_idx = int(i * 8 / n) if n > 0 else 0
                bucket_idx = min(7, bucket_idx)
                temp_buckets[bucket_idx].append(pid)
                
        # Calculate total candidates currently in temp_buckets
        total_in_temp = sum(len(b) for b in temp_buckets)
        
        # Stop condition: if the total number of profiles we just ranked is less than 2*top_k
        if total_in_temp < 2 * top_k:
            logger.info(f"Stopping condition met: {total_in_temp} profiles is less than 2 * top_k ({2 * top_k}).")
            # Flatten all 8 temp buckets (from best to worst)
            final_active_profiles = []
            for b in temp_buckets:
                final_active_profiles.extend(b)
            break
            
        # Otherwise, dismiss bottom 4 buckets and set top 4 buckets as the new active buckets
        for i in range(4):
            buckets[i] = temp_buckets[i]
            # Shuffle slightly within the bucket to prevent fixed pairings in the next round
            random.shuffle(buckets[i])
            
    logger.info(f"Swiss tournament completed. Executing final ranking on {len(final_active_profiles)} survivors.")
    
    # Do one final definitive ranking on the remaining pool
    final_profiles_dict = {pid: all_profiles[pid] for pid in final_active_profiles}
    final_sorted_ids = await rank_chunk(objective, final_profiles_dict)
    
    ranked_results = []
    for rank_idx, pid in enumerate(final_sorted_ids[:top_k]):
        ranked_results.append({
            "id": pid,
            "text": all_profiles[pid],
            "rank": rank_idx + 1
        })
        
    return ranked_results, len(ranked_results)
