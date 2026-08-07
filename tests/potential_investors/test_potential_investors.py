import os
import pytest
from skills.potential_investors.potential_investors import potential_investors
from lib.datasets.manifest import IngestionManifest
from lib.datasets.paths import dataset_location
from lib.storage import get_storage
from lib.datasets.paths import dataset_location_for_domain

@pytest.mark.asyncio
async def test_potential_investors_generation(mock_env, mocker, monkeypatch):
    """
    Tests that potential_investors correctly integrates the sub-modules,
    respects the cache, and writes the output file.
    """
    monkeypatch.setenv("RANKED_LLMS", "ollama/test_model:1b")
    get_storage().mkdir(
        dataset_location_for_domain("teststartup", "startups").raw_rel
    )
    # Mock startup_profile
    mock_startup = mocker.patch("skills.potential_investors.potential_investors.startup_profile")
    async def mock_startup_coro(*args, **kwargs):
        class FakeInsight:
            def content(self):
                return "Startup profile text"

        return [FakeInsight()]
    mock_startup.side_effect = mock_startup_coro

    # Mock config_load
    mock_config = mocker.patch("skills.potential_investors.potential_investors.config_load")
    mock_config.return_value = {
        "potential_investors": {
            "objective": "Match investors to this profile: {{startup_profile}}"
        }
    }

    # Mock ranking_persons
    mock_ranking = mocker.patch("skills.potential_investors.potential_investors.ranking_persons")
    async def mock_ranking_coro(*args, **kwargs):
        return "| Investor A | 90 | Good match |\n| Investor B | 80 | Okay match |"
    mock_ranking.side_effect = mock_ranking_coro

    async def fake_sync(dataset_names, **_kwargs):
        storage = get_storage()
        for dataset_name in dataset_names:
            location = dataset_location(dataset_name)
            manifest = IngestionManifest(storage, location.parsed_rel)
            manifest.indexed_dataset_revision = f"{location.slug}-revision"
            manifest.save()

    mocker.patch(
        "skills.potential_investors.potential_investors.sync_datasets",
        side_effect=fake_sync,
    )

    # Clear the storage cache before executing
    get_storage().rmtree("storage/startups/teststartup/insights")
    
    # Execute
    startup = "TestStartup"
    output = await potential_investors(startup)

    # Assert output contains our mock data (generate_output writes a markdown table)
    assert len(output) == 1
    assert "Investor A" in output[0].content()
    assert "Investor B" in output[0].content()
    assert "90" in output[0].content()

    # Assert File System
    expected_file = "storage/startups/teststartup/insights/potential-investors-teststartup-test-model-1b.md"
    assert get_storage().exists(expected_file)

    # Assert Cache Bypass
    output_cached = await potential_investors(startup)
    assert len(output_cached) == 1
    assert "Investor A" in output_cached[0].content()
    mock_startup.assert_called_once() # Should not be called again
