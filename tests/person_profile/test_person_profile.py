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

    mock_chunks = mocker.patch("skills.person_profile.person_profile.get_filtered_chunks")
    # Return a mock chunk object with required attributes
    class MockChunk:
        def __init__(self):
            self.document_name = "jane_resume.pdf"
            self.page_number = 1
            self.text = "Jane has 10 years of experience."
    async def mock_chunks_coro(*args, **kwargs):
        return [MockChunk()]
    mock_chunks.side_effect = mock_chunks_coro

    mock_config = mocker.patch("skills.person_profile.person_profile.config_load")
    mock_config.return_value = {
        "person_profile": {
            "query": "Who is {name}?",
            "llm_instructions": "Be concise."
        }
    }

    mock_linkedin = mocker.patch("skills.person_profile.person_profile.LinkedInAdapter")
    mock_linkedin_instance = mock_linkedin.return_value
    mock_linkedin_instance.get_profiles.return_value = [{"fullName": "Jane Doe", "headline": "CEO at Test"}]
    mock_linkedin_instance.get_filename_for_profile.return_value = "jane-doe.json"

    # 2. Execute
    name = "Jane Doe"
    dataset = "sictic_members"
    output = await person_profile(dataset_name=dataset, name=name)

    # 3. Assert Output
    assert output == "This is a mocked profile for Jane Doe."

    # 4. Assert File System
    gdrive_mount = mock_env["gdrive_mount"]
    expected_dir = os.path.join(gdrive_mount, "insights", dataset, "person_profile")
    expected_file = os.path.join(expected_dir, "jane-doe-test-model-1b.md")

    assert os.path.exists(expected_file), f"Expected file {expected_file} was not created."
    with open(expected_file, "r", encoding="utf-8") as f:
        content = f.read()
        assert content == "This is a mocked profile for Jane Doe."

    # 5. Assert Cache Bypass
    # If we call it again, it should use the cache (llm_chat shouldn't be called twice)
    output_cached = await person_profile(dataset_name=dataset, name=name)
    assert output_cached == "This is a mocked profile for Jane Doe."
    mock_llm.assert_called_once()  # Asserts it was only called during the FIRST execution
