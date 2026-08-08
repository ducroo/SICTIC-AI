import pytest

from lib.storage import get_storage
from lib.datasets.paths import dataset_location_for_domain
from skills.startup_traction.startup_traction import startup_traction


@pytest.mark.asyncio
async def test_startup_traction_does_not_cache_insufficient_context(mock_env, mocker):
    get_storage().mkdir(
        dataset_location_for_domain("bewe", "startups").raw_rel
    )
    mocker.patch(
        "skills.startup_traction.startup_traction.InsightFile.find",
        return_value=None,
    )
    mocker.patch("skills.startup_traction.startup_traction.sync_datasets")
    save = mocker.patch("skills.startup_traction.startup_traction.InsightFile.save")
    mocker.patch(
        "skills.startup_traction.startup_traction.config_load",
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
    mocker.patch(
        "skills.startup_traction.startup_traction.dataset_chat",
        return_value="INSUFFICIENT_CONTEXT",
    )
    with pytest.raises(ValueError, match="Insufficient indexed context"):
        await startup_traction("bewe")

    save.assert_not_called()
