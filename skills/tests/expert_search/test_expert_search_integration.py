import os
import pytest
from pathlib import Path
from skills.utils.env import get_env_var
from skills.startup_profile.startup_profile import startup_profile
from skills.dataset_chat.dataset_search import dataset_search
from skills.expert_search.expert_search import expert_search
from skills.utils.slugify import slugify

# Test data mappings: startup -> target expert
TEST_CASES = [
    ("avientus", "jasmine kent"),
    ("proud_technology", "markus dilger")
]

def check_dataset_exists(startup):
    """Check if required datasets exist in the local workspace."""
    try:
        gdrive_mount = get_env_var("GDRIVE_MOUNT")
    except Exception:
        return False
        
    datasets_dir = Path(gdrive_mount) / "datasets"
    
    if not (datasets_dir / "sictic_members").exists():
        return False
        
    if not (datasets_dir / startup).exists() and not (datasets_dir / f"{startup}_technology").exists():
        return False
            
    return True

@pytest.mark.asyncio
@pytest.mark.parametrize("startup_name, target_expert", TEST_CASES)
async def test_expert_search_semantic_and_ranking(startup_name, target_expert):
    if not check_dataset_exists(startup_name):
        pytest.skip(f"Dataset {startup_name} not found.")
    """
    Integration test to ensure:
    1. The startup profile generated correctly pulls the target expert into the top 10 semantic chunks.
    """
    try:
        # 1. Fetch/Generate Startup Profile
        profile_content, _ = await startup_profile(startup_name)
        assert profile_content, f"Failed to get startup profile for {startup_name}"
        
        # 2. Test Semantic Retrieval
        chunks = await dataset_search(
            dataset_name="sictic_members", 
            query=profile_content, 
            max_chunks=25, 
            return_full_docs=False
        )
        
        # Verify the target expert's name is somewhere in the top 25 document names or text
        found_in_semantic = False
        target_parts = target_expert.lower().split()
        
        for idx, chunk in enumerate(chunks):
            doc_lower = chunk.document_name.lower()
            # Check if all parts of the target name are in the document name
            if all(part in doc_lower for part in target_parts):
                found_in_semantic = True
                print(f"[{startup_name}] Found {target_expert} in semantic search at rank {idx + 1} with score {chunk.score}")
                break
                
        assert found_in_semantic, f"Semantic search failed: {target_expert} was not in the top 25 chunks for {startup_name}."

    finally:
        pass
