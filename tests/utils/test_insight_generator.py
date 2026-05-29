import pytest

from lib.insight_generator import generate_dataset_insight


@pytest.mark.asyncio
async def test_generate_dataset_insight_does_not_cache_insufficient_context(mock_env, mocker):
    mocker.patch("lib.insight_generator.check_insight_refresh", return_value=(True, None, None))
    mocker.patch(
        "lib.insight_generator.config_load",
        return_value={
            "startup_traction": {
                "query": "Find traction.",
                "llm_instructions": "Use only context.",
            },
            "dataset_chat": {
                "fallback_trigger": "INSUFFICIENT_CONTEXT",
            },
        },
    )
    mocker.patch("lib.insight_generator.dataset_chat", return_value="INSUFFICIENT_CONTEXT")
    mock_storage = mocker.patch("lib.insight_generator.get_storage")

    with pytest.raises(ValueError, match="Insufficient indexed context"):
        await generate_dataset_insight("bewe", "startup_traction", "startup_traction")

    mock_storage.return_value.write_text.assert_not_called()
