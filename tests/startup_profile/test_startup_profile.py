import pytest

from lib.storage import get_storage
from lib.datasets.paths import dataset_location_for_domain
from skills.startup_profile.startup_profile import startup_profile


@pytest.mark.asyncio
async def test_startup_profile_saves_empty_context_response(mock_env, mocker):
    get_storage().mkdir(
        dataset_location_for_domain("avientus", "startups").raw_rel
    )
    mocker.patch(
        "skills.startup_profile.startup_profile.InsightFile.find",
        return_value=None,
    )
    mocker.patch("skills.startup_profile.startup_profile.sync_datasets")
    save = mocker.patch(
        "skills.startup_profile.startup_profile.InsightFile.save"
    )
    mocker.patch(
        "skills.startup_profile.startup_profile.load_repository_config",
        return_value={
            "query": "Profile this startup.",
            "llm_instructions": "Use only context.",
        },
    )
    mocker.patch(
        "skills.startup_profile.startup_profile.dataset_chat",
        return_value="INSUFFICIENT_CONTEXT",
    )
    result = await startup_profile("Avientus")

    save.assert_called_once_with("INSUFFICIENT_CONTEXT")
    assert len(result) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("empty_output", ["", "   "])
async def test_startup_profile_rejects_empty_llm_output(mock_env, mocker, empty_output):
    get_storage().mkdir(
        dataset_location_for_domain("avientus", "startups").raw_rel
    )
    mocker.patch(
        "skills.startup_profile.startup_profile.InsightFile.find",
        return_value=None,
    )
    mocker.patch("skills.startup_profile.startup_profile.sync_datasets")
    save = mocker.patch(
        "skills.startup_profile.startup_profile.InsightFile.save"
    )
    mocker.patch(
        "skills.startup_profile.startup_profile.load_repository_config",
        return_value={
            "query": "Profile this startup.",
            "llm_instructions": "Use only context.",
        },
    )
    mocker.patch(
        "skills.startup_profile.startup_profile.dataset_chat",
        return_value=empty_output,
    )

    with pytest.raises(ValueError, match="empty response"):
        await startup_profile("Avientus")

    save.assert_not_called()


@pytest.mark.asyncio
async def test_startup_profile_splits_query_lines_for_retrieval(mock_env, mocker):
    get_storage().mkdir(
        dataset_location_for_domain("avientus", "startups").raw_rel
    )
    mocker.patch(
        "skills.startup_profile.startup_profile.InsightFile.find",
        return_value=None,
    )
    mocker.patch("skills.startup_profile.startup_profile.sync_datasets")
    mocker.patch("skills.startup_profile.startup_profile.InsightFile.save")
    mocker.patch(
        "skills.startup_profile.startup_profile.load_repository_config",
        return_value={
            "query": "1. Oneliner\n\n2. Industry\n3. Technology",
            "llm_instructions": "Use only context.",
        },
    )
    chat = mocker.patch(
        "skills.startup_profile.startup_profile.dataset_chat",
        return_value="Profile output",
    )

    await startup_profile("Avientus")

    chat.assert_awaited_once_with(
        dataset_name="avientus",
        queries=["1. Oneliner", "2. Industry", "3. Technology"],
        prompt=(
            "Query: 1. Oneliner\n\n2. Industry\n\n3. Technology\n\n"
            "Instructions: Use only context."
        ),
    )
