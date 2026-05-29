import pytest

from skills.startup_profile.startup_profile import startup_profile


@pytest.mark.asyncio
async def test_startup_profile_does_not_cache_empty_context_response(mocker):
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
