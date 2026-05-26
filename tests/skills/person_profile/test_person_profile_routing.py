import pytest
from unittest.mock import patch, MagicMock
from skills.person_profile.person_profile import person_profile

@pytest.mark.asyncio
async def test_person_profile_routing_and_fuzzy_match():
    """
    Tests the routing and fuzzy matching logic in the orchestrator.
    We mock the underlying adapters to strictly control what the dataset "contains".
    """
    
    dataset_name = "test_dataset"
    
    from lib.models.person import Person
    # Mock data to return from the adapter
    mock_profiles = [
        Person(linkedinID="johannes-aicher", full_name="Johannes Aicher", linkedin_profile={}),
        Person(linkedinID="urs-gubser", full_name="Urs Gubser", linkedin_profile={}),
        Person(linkedinID="ghost-user", full_name="Ghost User", linkedin_profile={})
    ]

    with patch('skills.person_profile.person_profile.persons_in_dataset') as mock_discover, \
         patch('skills.person_profile.person_profile.LinkedInAdapter') as mock_adapter_cls, \
         patch('skills.person_profile.person_profile._generate_single_profile') as mock_generate:
        
        # Setup mocks
        mock_discover.return_value = [Person(linkedinID="johannes-aicher"), Person(linkedinID="urs-gubser"), Person(linkedinID="ghost-user")]
        
        mock_adapter_instance = MagicMock()
        # Dynamic mock for get_profiles to mirror real behavior
        def mock_get_profiles_side_effect(person_list):
            results = []
            for p in person_list:
                # Find matching mock profile, or return the requested person untouched
                match = next((mp for mp in mock_profiles if mp.matches(p)), p)
                results.append(match)
            return results
            
        mock_adapter_instance.get_profiles.side_effect = mock_get_profiles_side_effect
        mock_adapter_cls.return_value = mock_adapter_instance
        
        mock_generate.return_value = "Mocked Report Content"
        
        # --- TEST 2.1: Full Dataset (names=None) ---
        result_full = await person_profile(dataset_name, names=None)
        
        assert len(result_full) == 3
        assert any(p.full_name == "Johannes Aicher" for p in result_full)
        assert mock_generate.call_count == 3
        mock_generate.reset_mock()
        
        # --- TEST 2.2: Exact Match ---
        result_exact = await person_profile(dataset_name, names="Johannes Aicher")
        
        assert len(result_exact) == 1
        assert isinstance(result_exact[0], Person)
        assert mock_generate.call_count == 1
        
        # Verify the correct wrapper was passed to the generator
        called_wrapper = mock_generate.call_args[0][1]
        assert called_wrapper.linkedinID == "johannes-aicher"
        mock_generate.reset_mock()
        
        # --- TEST 2.3: Substring Match ---
        result_sub = await person_profile(dataset_name, names=["Aicher", "Urs"])
        
        assert len(result_sub) == 2
        assert mock_generate.call_count == 2
        mock_generate.reset_mock()

        # --- TEST 2.4: Fuzzy Match (Typos) ---
        result_fuzzy = await person_profile(dataset_name, names="Johness Acher")
        
        assert len(result_fuzzy) == 1
        assert mock_generate.call_count == 1
        
        # Verify it mapped the typo to the canonical user
        called_wrapper = mock_generate.call_args[0][1]
        assert called_wrapper.linkedinID == "johannes-aicher"
        mock_generate.reset_mock()
        
        # --- TEST: Unmatched ---
        result_miss = await person_profile(dataset_name, names="Batman")
        
        assert len(result_miss) == 1
        assert mock_generate.call_count == 1
        
        # Verify it passed the unmatched requested name down the pipeline
        called_wrapper = mock_generate.call_args[0][1]
        assert called_wrapper.full_name == "Batman"
