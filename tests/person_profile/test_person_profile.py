import os
import pytest
from skills.person_profile.person_profile import (
    _ensure_profile_metadata_header,
    _generate_single_profile,
    person_profile,
)
from lib.models.person import Person

@pytest.mark.asyncio
async def test_person_profile_generation(mock_env, mocker, monkeypatch):
    """
    Tests that person_profile correctly aggregates data, generates a file,
    and formats the output path correctly without calling the real LLM.
    """
    monkeypatch.setenv("RANKED_LLMS", "ollama/test_model:1b")
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

    mock_linkedin = mocker.patch("skills.person_profile.person_profile.LinkedInAdapter")
    mock_linkedin_instance = mock_linkedin.return_value
    mock_linkedin_instance.get_profiles.return_value = [
        Person(
            full_name="Jane Doe",
            linkedin_id="jane-doe",
            email_addresses=["jane@example.com"],
            linkedin_profile={"headline": "CEO at Test"},
        )
    ]
    mock_linkedin_instance.get_filename_for_profile.return_value = "jane-doe.json"

    # Clear the storage cache before executing to ensure we aren't picking up files from a previous run
    from lib.storage import get_storage
    get_storage().rmtree("storage/community/sictic-members/insights/person-profile")
    
    # 2. Execute
    name = "Jane Doe"
    dataset = "sictic_members"
    output = await person_profile(dataset_name=dataset, names=name)

    # 3. Assert Output
    expected_content = "\n".join(
        [
            "Full-name: Jane Doe",
            "linkedin-id: jane-doe",
            "Email-addresses: jane@example.com",
            "",
            "This is a mocked profile for Jane Doe.",
        ]
    )
    assert len(output) == 1 and output[0].person_profile == expected_content

    # 4. Assert File System
    expected_file = "storage/community/sictic-members/insights/person-profile/jane-doe-test-model-1b.md"

    from lib.storage import get_storage
    storage = get_storage()
    assert storage.exists(expected_file), f"Expected file {expected_file} was not created."
    content = storage.read_text(expected_file)
    assert content == expected_content
    prompt = mock_llm.call_args.kwargs["prompt"]
    assert "Person metadata:\nFull-name: Jane Doe\nlinkedin-id: jane-doe\nEmail-addresses: jane@example.com" in prompt
    assert "### DOSSIER DOCUMENTS" in prompt
    assert "Jane has 10 years of experience." in prompt
    assert "### LINKEDIN PROFILE" in prompt
    mock_dossier.assert_awaited_once()

    # 5. Assert Cache Bypass
    # If we call it again, it should use the cache (llm_chat shouldn't be called twice)
    output_cached = await person_profile(dataset_name=dataset, names=name)
    assert len(output_cached) == 1 and output_cached[0].person_profile == expected_content
    mock_llm.assert_called_once()  # Asserts it was only called during the FIRST execution


@pytest.mark.asyncio
async def test_person_profile_can_explicitly_skip_dataset_context(mock_env, mocker, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/test_model:1b")
    mocker.patch(
        "skills.person_profile.person_profile.config_load",
        return_value={
            "person_profile": {
                "query": "Who is {{name}}?",
                "llm_instructions": "Be concise.",
            }
        },
    )
    mock_llm = mocker.patch(
        "skills.person_profile.person_profile.llm_chat",
        return_value="LinkedIn-only profile.",
    )
    mock_dossier = mocker.patch("skills.person_profile.person_profile.build_person_dossier")
    person = Person(
        full_name="Jane Doe",
        linkedin_id="jane-doe",
        linkedin_profile={"headline": "CEO at Test"},
    )

    await _generate_single_profile(
        "sictic-members",
        person,
        include_dataset_context=False,
    )

    mock_dossier.assert_not_awaited()
    prompt = mock_llm.call_args.kwargs["prompt"]
    assert "### LINKEDIN PROFILE" in prompt
    assert "### DOSSIER DOCUMENTS" not in prompt


def test_ensure_profile_metadata_header_adds_header_to_legacy_cached_content():
    person = Person(full_name="Jane Doe", linkedin_id="jane-doe", email_addresses=["jane@example.com"])

    assert _ensure_profile_metadata_header(person, "Legacy body") == "\n".join(
        [
            "Full-name: Jane Doe",
            "linkedin-id: jane-doe",
            "Email-addresses: jane@example.com",
            "",
            "Legacy body",
        ]
    )
