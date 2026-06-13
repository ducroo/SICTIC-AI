import pytest

from lib.storage import get_storage
from lib.storage_domains import dataset_location_for_domain
from skills.startup_profile.startup_profile import startup_profile


@pytest.mark.asyncio
async def test_startup_profile_does_not_cache_empty_context_response(mock_env, mocker):
    get_storage().mkdir(
        dataset_location_for_domain("avientus", "startups").raw_rel
    )
    mocker.patch(
        "skills.startup_profile.startup_profile.check_insight_refresh",
        return_value=(True, None, None),
    )
    mocker.patch(
        "skills.startup_profile.startup_profile.config_load",
        return_value={
            "startup_profile": {
                "query": "Profile this startup.",
                "llm_instructions": "Use only context.",
            }
        },
    )
    mocker.patch(
        "skills.startup_profile.startup_profile.dataset_chat",
        return_value="INSUFFICIENT_CONTEXT",
    )
    mock_storage = mocker.patch("skills.startup_profile.startup_profile.get_storage")

    with pytest.raises(ValueError, match="Insufficient indexed context"):
        await startup_profile("Avientus")

    mock_storage.return_value.write_text.assert_not_called()


@pytest.mark.asyncio
async def test_startup_profile_splits_query_lines_for_retrieval(mock_env, mocker):
    get_storage().mkdir(
        dataset_location_for_domain("avientus", "startups").raw_rel
    )
    mocker.patch(
        "skills.startup_profile.startup_profile.check_insight_refresh",
        return_value=(True, None, None),
    )
    mocker.patch(
        "skills.startup_profile.startup_profile.config_load",
        return_value={
            "startup_profile": {
                "query": "1. Oneliner\n\n2. Industry\n3. Technology",
                "llm_instructions": "Use only context.",
            }
        },
    )
    chat = mocker.patch(
        "skills.startup_profile.startup_profile.dataset_chat",
        return_value="Profile output",
    )

    await startup_profile("Avientus")

    chat.assert_awaited_once_with(
        dataset_name="avientus",
        questions=["1. Oneliner", "2. Industry", "3. Technology"],
        llm_instructions="Use only context.",
    )
