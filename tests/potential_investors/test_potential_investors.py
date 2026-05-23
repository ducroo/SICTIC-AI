import os
import pytest
from skills.potential_investors.potential_investors import potential_investors

@pytest.mark.asyncio
async def test_potential_investors_generation(mock_env, mocker):
    """
    Tests that potential_investors correctly integrates the sub-modules,
    respects the cache, and writes the output file.
    """
    # Mock startup_profile
    mock_startup = mocker.patch("skills.potential_investors.potential_investors.startup_profile")
    async def mock_startup_coro(*args, **kwargs):
        return ("Startup profile text", "path")
    mock_startup.side_effect = mock_startup_coro

    # Mock config_load
    mock_config = mocker.patch("skills.potential_investors.potential_investors.config_load")
    mock_config.return_value = {
        "potential_investors": {
            "objective": "Match investors to this profile: {{startup_profile}}"
        }
    }

    # Mock people_ranking
    mock_ranking = mocker.patch("skills.potential_investors.potential_investors.people_ranking")
    async def mock_ranking_coro(*args, **kwargs):
        return "| Investor A | 90 | Good match |\n| Investor B | 80 | Okay match |"
    mock_ranking.side_effect = mock_ranking_coro

    # Clear the storage cache before executing
    from lib.storage import get_storage
    get_storage().rmtree("insights/teststartup")
    
    # Execute
    startup = "TestStartup"
    output = await potential_investors(startup)

    # Assert output contains our mock data (generate_output writes a markdown table)
    assert "Investor A" in output
    assert "Investor B" in output
    assert "90" in output

    # Assert File System
    expected_file = "insights/teststartup/potential-investors-teststartup-test-model-1b.md"
    from lib.storage import get_storage
    assert get_storage().exists(expected_file)

    # Assert Cache Bypass
    output_cached = await potential_investors(startup)
    assert "Investor A" in output_cached
    mock_startup.assert_called_once() # Should not be called again
