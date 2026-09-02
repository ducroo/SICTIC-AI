import pytest
from skills.potential_investors.potential_investors import potential_investors
from lib.storage import get_storage
from lib.datasets.paths import dataset_location_for_domain

@pytest.mark.asyncio
async def test_potential_investors_generation(mock_env, mocker, monkeypatch):
    """
    Tests that potential_investors correctly integrates the sub-modules,
    recomputes explicitly requested rankings and writes the output file.
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

    mock_config = mocker.patch(
        "skills.potential_investors.potential_investors.load_repository_config"
    )
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

    # Ranking skills deliberately sit outside dataset freshness caching.
    output_recomputed = await potential_investors(startup)
    assert len(output_recomputed) == 1
    assert "Investor A" in output_recomputed[0].content()
    assert mock_startup.call_count == 2
    assert mock_ranking.call_count == 2
