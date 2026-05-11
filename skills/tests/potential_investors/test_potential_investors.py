import os
import pytest
from skills.potential_investors.potential_investors import potential_investors

@pytest.mark.asyncio
async def test_potential_investors_generation(mock_env, mocker):
    """
    Tests that potential_investors correctly integrates the sub-modules,
    respects the cache, and writes the output file.
    """
    # Mock data_loader
    mock_fetch = mocker.patch("skills.potential_investors.potential_investors.fetch_data")
    mock_fetch.return_value = ("Startup profile text", ["Investor A", "Investor B"])

    # Mock semantic_search
    mock_search = mocker.patch("skills.potential_investors.potential_investors.perform_semantic_search")
    async def mock_search_coro(*args, **kwargs):
        return ["Investor A", "Investor B"]
    mock_search.side_effect = mock_search_coro

    # Mock llm_ranking
    mock_rank = mocker.patch("skills.potential_investors.potential_investors.rank_investors")
    async def mock_rank_coro(*args, **kwargs):
        return [
            {"investor_name": "Investor A", "score": 90, "rationale": "Good match"},
            {"investor_name": "Investor B", "score": 80, "rationale": "Okay match"}
        ]
    mock_rank.side_effect = mock_rank_coro

    # Execute
    startup = "TestStartup"
    output = await potential_investors(startup)

    # Assert output contains our mock data (generate_output writes a markdown table)
    assert "Investor A" in output
    assert "Investor B" in output
    assert "90" in output

    # Assert File System
    gdrive_mount = mock_env["gdrive_mount"]
    expected_dir = os.path.join(gdrive_mount, "insights", "teststartup")
    expected_file = os.path.join(expected_dir, "teststartup-potential-investors-test-model-1b.md")
    assert os.path.exists(expected_file)

    # Assert Cache Bypass
    output_cached = await potential_investors(startup)
    assert "Investor A" in output_cached
    mock_fetch.assert_called_once() # Should not be called again
