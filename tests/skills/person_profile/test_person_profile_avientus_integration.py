import pytest
from skills.person_profile.person_profile import person_profile

@pytest.mark.asyncio
@pytest.mark.live
async def test_person_profile_avientus_integration():
    """
    Integration test against the materialized Avientus dataset to assert 
    the full hydration of a Person profile including LinkedIn and Data Room mentions.
    """
    # 1. Execute Person Profile for Johannes Aicher
    persons = await person_profile(dataset_name="avientus", names="Johannes Aicher")
    
    assert len(persons) == 1, "Should resolve to exactly one Person."
    p = persons[0]
    
    # 2. Assert Canonical Fields
    assert p.linkedin_id == "johannes-aicher"
    assert p.full_name == "Johannes Aicher"
    
    # 3. Assert LinkedIn Hydration
    assert bool(p.linkedin_profile) is True
    assert "firstName" in p.linkedin_profile
    assert "lastName" in p.linkedin_profile
    
    # 4. Assert Qdrant Discovery & Chunk Parsing
    # We expect a high number of mentions since he is the CEO
    assert len(p.mentions) >= 20, "Should have discovered at least 20 mention chunks."
    
    mention_docs = {m.document_name for m in p.mentions}
    
    # Ensure specific critical documents were picked up in his orbit
    assert any("CVs of Founders" in d or "CVs_Founder" in d for d in mention_docs), f"CVs not found. Found: {mention_docs}"
    assert any("Avientus_Cap_Table" in d for d in mention_docs), f"Cap Table not found. Found: {mention_docs}"
