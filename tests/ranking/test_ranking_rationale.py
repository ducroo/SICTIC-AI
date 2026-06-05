import pytest

from skills.ranking.ranking_rationale import ranking_rationale


@pytest.mark.asyncio
async def test_ranking_rationale_only_uses_id_and_rationale(mocker):
    mocker.patch(
        "skills.ranking.ranking_rationale.config_load",
        return_value={
            "ranking_rationale": {
                "rationale_instructions": "{{objective}}\n{{profiles_text}}",
            }
        },
    )

    mock_llm = mocker.patch("skills.ranking.ranking_rationale.llm_chat")
    mock_llm.return_value = '{"results": [{"id": "urs-gubser", "rationale": "Strong fit."}]}'

    ranked_items = [{"id": "urs-gubser", "text": "Profile text", "rank": 1}]

    result = await ranking_rationale(ranked_items, objective="Find experts")

    assert result == [{"id": "urs-gubser", "text": "Profile text", "rank": 1, "rationale": "Strong fit."}]
    assert "profile_name" not in result[0]
    assert "balanced_rationale_for_ranking" not in result[0]
