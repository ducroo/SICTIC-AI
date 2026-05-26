import os
import pytest
from skills.person_profile.person_profile import person_profile

@pytest.mark.asyncio
async def test_person_profile_generation(mock_env, mocker):
    """
    Tests that person_profile correctly aggregates data, generates a file,
    and formats the output path correctly without calling the real LLM.
    """
    # 1. Mock external dependencies
    mock_llm = mocker.patch("skills.person_profile.person_profile.llm_chat")
    async def mock_llm_coro(*args, **kwargs):
        return "This is a mocked profile for Jane Doe."
    mock_llm.side_effect = mock_llm_coro

    from skills.dataset_chat.core.models import Chunk
    mock_dossier = mocker.patch("skills.person_profile.person_profile.build_person_dossier")
    async def mock_dossier_coro(*args, **kwargs):
        d_chunk = Chunk(chunk_id="1", document_name="jane_resume.pdf", page_number="all", last_modified=0.0, text="Jane has 10 years of experience.", score=1.0)
        m_chunk = Chunk(chunk_id="2", document_name="some_file.md", page_number=1, last_modified=0.0, text="Jane is mentioned here.", score=1.0)
        return [d_chunk], [m_chunk]
    mock_dossier.side_effect = mock_dossier_coro

    mock_config = mocker.patch("skills.person_profile.person_profile.config_load")
    mock_config.return_value = {
        "person_profile": {
            "query": "Who is {name}?",
            "llm_instructions": "Be concise."
        }
    }

    from lib.models.person import Person
    mock_linkedin = mocker.patch("skills.person_profile.person_profile.LinkedInAdapter")
    mock_linkedin_instance = mock_linkedin.return_value
    mock_linkedin_instance.get_profiles.return_value = [Person(full_name="Jane Doe", linkedinID="jane-doe", linkedin_profile={"headline": "CEO at Test"})]
    mock_linkedin_instance.get_filename_for_profile.return_value = "jane-doe.json"

    # Clear the storage cache before executing to ensure we aren't picking up files from a previous run
    from lib.storage import get_storage
    get_storage().rmtree("insights/sictic-members/person-profile")
    
    # 2. Execute
    name = "Jane Doe"
    dataset = "sictic_members"
    output = await person_profile(dataset_name=dataset, names=name)

    # 3. Assert Output
    assert len(output) == 1 and output[0].person_profile == "This is a mocked profile for Jane Doe."

    # 4. Assert File System
    expected_file = "insights/sictic-members/person-profile/jane-doe-test-model-1b.md"

    from lib.storage import get_storage
    storage = get_storage()
    assert storage.exists(expected_file), f"Expected file {expected_file} was not created."
    content = storage.read_text(expected_file)
    assert content == "This is a mocked profile for Jane Doe."

    # 5. Assert Cache Bypass
    # If we call it again, it should use the cache (llm_chat shouldn't be called twice)
    output_cached = await person_profile(dataset_name=dataset, names=name)
    assert len(output_cached) == 1 and output_cached[0].person_profile == "This is a mocked profile for Jane Doe."
    mock_llm.assert_called_once()  # Asserts it was only called during the FIRST execution
