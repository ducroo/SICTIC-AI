import asyncio
import random
import json
import sys
from typing import Dict, List, Any, Tuple
from pydantic import BaseModel, Field

from skills.llm_chat.llm_chat import llm_chat
from skills.config_load.config_load import config_load
from lib.json_parser import repair_json_payload
from lib.logger import get_logger

logger = get_logger(__name__)

ORDERED_CATEGORIES = ["MUCH_BETTER", "BETTER", "WORSE", "MUCH_WORSE"]

def get_empty_buckets() -> Dict[str, List[str]]:
    return {cat: [] for cat in ORDERED_CATEGORIES}

class CategorizationResult(BaseModel):
    profile_id: str
    category: str = Field(description=f"One of: {', '.join(ORDERED_CATEGORIES)}")

class BatchCategorizationResult(BaseModel):
    results: List[CategorizationResult]

class RankedProfilesResult(BaseModel):
    ranked_profile_ids: List[str] = Field(
        description="List of profile IDs ordered from best to worst",
        alias="ranked_profiles_ids"
    )

    class Config:
        populate_by_name = True

async def bucketing_profiles(objective: str, profiles: Dict[str, str], pivot_id: str, pivot_text: str) -> Dict[str, List[str]]:
    """
    Categorizes a batch of profiles against a pivot based on an objective.
    Returns a dictionary mapping categories to lists of profile IDs.
    """
    # Fetch prompt template from config
    config = config_load()
    prompt = config["find_top_k"]["bucketing_instructions"]
    
    # Shuffle for positional bias mitigation
    profile_ids = list(profiles.keys())
    logger.info(f"Starting bucketing_profiles for {len(profile_ids)} candidates against pivot '{pivot_id}'.")
    random.shuffle(profile_ids)
    
    profiles_text = "\n\n".join([f"ID: {i}\n{profiles[i]}" for i in profile_ids])
    prompt = prompt.replace("{{objective}}", objective)
    prompt = prompt.replace("{{pivot_text}}", pivot_text)
    prompt = prompt.replace("{{profiles_text}}", profiles_text)
    prompt = prompt.replace("{{n_profiles}}", str(len(profiles)))
    prompt = prompt.replace("{{IDs_profiles}}", ", ".join(profiles))
    prompt = prompt.replace("{{ID_pivot}}", pivot_id)
    
    logger.info(f"bucketing_profiles processing the following {len(profiles)} profiles: {", ".join(profiles)}")
    #logger.info(f"bucketing_profiles prompt: \n\n {prompt}")
    
    try:
        response_content = await llm_chat(prompt, response_format=BatchCategorizationResult)
        if not response_content:
            buckets = get_empty_buckets()
            buckets["SIMILAR"] = profile_ids
            return buckets
            
        parsed_dict = repair_json_payload(response_content)
        
        # Safe-guard if model outputs "profiles" instead of "results"
        if "profiles" in parsed_dict and "results" not in parsed_dict:
            parsed_dict["results"] = parsed_dict.pop("profiles")
            
        parsed_data = BatchCategorizationResult.model_validate(parsed_dict)
        
        buckets = get_empty_buckets()
        for res in parsed_data.results:
            cat = res.category.upper()
            if cat in buckets and res.profile_id in profiles:
                buckets[cat].append(res.profile_id)
            else:
                if res.profile_id in profiles:
                    buckets["SIMILAR"].append(res.profile_id)
        logger.info(f"bucketing_profiles results: {buckets}")

        return buckets
    except Exception as e:
        logger.error(f"Error in bucketing_profiles: {e}")
        buckets = get_empty_buckets()
        buckets["SIMILAR"] = profile_ids
        return buckets

async def find_median_pivot(objective: str, profiles: Dict[str, str]) -> str:
    """
    Ranks a small set of profiles (e.g., 5) and returns the median profile ID to use as a pivot.
    """
    profile_ids = list(profiles.keys())
    logger.info(f"Starting find_median_pivot with {len(profile_ids)} candidates: {",".join(profile_ids)}.")
    if len(profile_ids) <= 2:
        return profile_ids[0]
        
    config = config_load()
    prompt = config["find_top_k"]["pivot_instructions"]
        
    random.shuffle(profile_ids)
    profiles_text = "\n\n".join([f"ID: {i}\n{profiles[i]}" for i in profile_ids])
    prompt = prompt.replace("{{profiles_text}}", profiles_text)
    prompt = prompt.replace("{{objective}}", objective)
    prompt = prompt.replace("{{n_profiles}}", str(len(profiles)))
    prompt = prompt.replace("{{IDs_profiles}}", ",".join(profiles))
    #logger.info(f"median_pivot prompt: \n\n {prompt}")
 
    try:
        response_content = await llm_chat(prompt, response_format=RankedProfilesResult)
        if not response_content:
            fallback_pivot = profile_ids[len(profile_ids) // 2]
            logger.info(f"median_pivot returned empty; defaulted to fallback ranking {profile_ids} and selected '{fallback_pivot}' as the median pivot.")
            return fallback_pivot
            
        parsed_dict = repair_json_payload(response_content)
        parsed_data = RankedProfilesResult.model_validate(parsed_dict)
        
        valid_ranked = [i for i in parsed_data.ranked_profile_ids if i in profiles]
        if valid_ranked:
            pivot = valid_ranked[len(valid_ranked) // 2]
            logger.info(f"median_pivot ranked {valid_ranked} and selected '{pivot}' as the median pivot.")
            return pivot
    except Exception as e:
        logger.error(f"Error in find_median_pivot: {e}")
        
    fallback_pivot = profile_ids[len(profile_ids) // 2]
    logger.info(f"median_pivot encountered an error; defaulted to fallback ranking {profile_ids} and selected '{fallback_pivot}' as the median pivot.")
    return fallback_pivot

async def process_set(objective: str, profiles_subset: Dict[str, str]) -> Dict[str, List[str]]:
    """
    Processes a set of profiles by picking a random pivot and categorizing the rest in chunks.
    """
    if len(profiles_subset) <= 1:
        return {"SIMILAR": list(profiles_subset.keys())}
        
    profile_ids = list(profiles_subset.keys())
    
    # Select up to 3 profiles to find a good median pivot
    sample_size = min(3, len(profile_ids))
    sample_ids = random.sample(profile_ids, sample_size)
    sample_profiles = {i: profiles_subset[i] for i in sample_ids}
    
    pivot_id = await find_median_pivot(objective, sample_profiles)
    pivot_text = profiles_subset[pivot_id]
    
    remaining_ids = [i for i in profile_ids if i != pivot_id]
    
    # Chunk remaining profiles into batches of up to 4
    chunk_size = 4
    chunks = [remaining_ids[i:i + chunk_size] for i in range(0, len(remaining_ids), chunk_size)]
    
    tasks = []
    for chunk in chunks:
        chunk_profiles = {i: profiles_subset[i] for i in chunk}
        tasks.append(bucketing_profiles(objective, chunk_profiles, pivot_id, pivot_text))
        
    results = await asyncio.gather(*tasks)
    
    # Aggregate results
    aggregated = get_empty_buckets()
    aggregated["SIMILAR"] = [pivot_id]
    for res in results:
        for cat in aggregated:
            aggregated[cat].extend(res.get(cat, []))
            
    return aggregated

async def find_top_k(objective: str, all_profiles: Dict[str, str], top_k: int = 8) -> Tuple[List[Dict[str, Any]], int]:
    """
    Finds the top_k profiles from all_profiles based on the objective.
    Returns a tuple containing:
    - A sorted list of dictionaries with keys: 'id', 'text', 'rank'.
    - The actual_top_k used (which may be slightly larger than top_k due to ties at the boundary).
    """
    ranks = {}
    current_rank = 1
    logger.info(f"Starting find_top_k with {len(all_profiles)} total candidates for top_k={top_k}.")
    
    async def recursive_rank(profiles_subset: Dict[str, str], target_top_k: int, start_rank: int):
        nonlocal current_rank
        logger.info(f"Entering recursive_rank with {len(profiles_subset)} candidates, target_top_k={target_top_k}, start_rank={start_rank}.")
        if not profiles_subset:
            return
            
        if len(profiles_subset) == 1:
            profile_id = list(profiles_subset.keys())[0]
            ranks[profile_id] = start_rank
            current_rank = start_rank + 1
            return
            
        buckets = await process_set(objective, profiles_subset)
        
        cumulative_length = 0
        for cat in ORDERED_CATEGORIES:
            bucket_ids = buckets[cat]
            if not bucket_ids:
                continue
                
            bucket_len = len(bucket_ids)
            
            if cumulative_length >= target_top_k or cumulative_length + bucket_len < target_top_k * 1.2:
                # Accept the whole bucket at the current rank level
                for profile_id in bucket_ids:
                    ranks[profile_id] = current_rank
                current_rank += 1
                cumulative_length += bucket_len
            else:
                # We need to sub-divide this bucket to get closer to top_k
                bucketing_profiles = {i: all_profiles[i] for i in bucket_ids}
                await recursive_rank(bucketing_profiles, target_top_k - cumulative_length, current_rank)
                cumulative_length += bucket_len
                    
    await recursive_rank(all_profiles, top_k, current_rank)
    
    # Fill in any missing profiles with the lowest rank
    max_rank = max(ranks.values()) if ranks else 1
    for profile_id in all_profiles:
        if profile_id not in ranks:
            ranks[profile_id] = max_rank + 1
            
    # Build final sorted list of dicts
    ranked_results = []
    sorted_ranks = sorted(ranks.items(), key=lambda profile: profile[1])
    
    for profile_id, rank in sorted_ranks:
        ranked_results.append({
            "id": profile_id,
            "text": all_profiles[profile_id],
            "rank": rank
        })
        
    r_target = ranked_results[min(top_k, len(ranked_results)) - 1]["rank"] if ranked_results else 0
    actual_top_k = sum(1 for profile in ranked_results if profile["rank"] <= r_target)
            
    return ranked_results, actual_top_k
