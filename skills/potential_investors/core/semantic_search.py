from typing import List
from skills.utils.logger import get_logger
from skills.dataset_chat.dataset_search import dataset_search
from skills.utils.slugify import slugify

logger = get_logger(__name__)

async def perform_semantic_search(profile_content: str, target_investors: List[str], max_investors: int) -> List[str]:
    logger.info("Performing semantic search on investor appetites...")
    chunks = await dataset_search(
        dataset_name="investor_appetite",
        query=profile_content,
        max_chunks=200,
        return_full_docs=True
    )
    
    if not chunks:
        logger.warning("No matches found in semantic search.")
        return []
        
    filtered_investors = []
    investor_scores = []
    seen = set()
    
    clean_targets = {slugify(inv): inv for inv in target_investors}
    
    for chunk in chunks:
        doc_name = chunk.document_name
        score = getattr(chunk, 'score', 0.0)
        
        matched_inv = None
        for ct, inv_name in clean_targets.items():
            if ct in doc_name:
                matched_inv = inv_name
                break
                
        if matched_inv and matched_inv not in seen:
            seen.add(matched_inv)
            filtered_investors.append(matched_inv)
            investor_scores.append(score)
            
    # Calculate statistics based on all retrieved investors
    if investor_scores:
        overall_high = max(investor_scores)
        overall_low = min(investor_scores)
        overall_avg = sum(investor_scores) / len(investor_scores)
        
        top_slice = investor_scores[:max_investors]
        reserve_slice = investor_scores[max_investors:max_investors*2]
        
        top_avg = sum(top_slice) / len(top_slice) if top_slice else 0.0
        cutoff_score = top_slice[-1] if top_slice else 0.0
        reserve_avg = sum(reserve_slice) / len(reserve_slice) if reserve_slice else 0.0
        
        logger.info(
            f"Semantic Search Stats: "
            f"Considered {len(filtered_investors)} investors out of {len(target_investors)} total target investors. | "
            f"Overall -> High: {overall_high:.4f}, Low: {overall_low:.4f}, Avg: {overall_avg:.4f} | "
            f"Top {len(top_slice)} -> Avg: {top_avg:.4f}, Cutoff: {cutoff_score:.4f} | "
            f"Reserves ({len(reserve_slice)}) -> Avg: {reserve_avg:.4f}"
        )
    else:
        logger.warning("No valid investors extracted from chunks to calculate scores.")
            
    top_candidates = filtered_investors[:max_investors * 2]
    logger.info(f"Returning {len(top_candidates)} top candidates after semantic search.")
    
    return top_candidates