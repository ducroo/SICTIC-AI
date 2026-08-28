import pytest
import json
from pathlib import Path

from skills.ranking.ranking_rationale import ranking_rationale


RESPONSE_SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "config/ranking_rationale/response_schema.json"
    ).read_text(encoding="utf-8")
)


@pytest.mark.asyncio
async def test_ranking_rationale_only_uses_id_and_rationale(mocker):
    mocker.patch(
        "skills.ranking.ranking_rationale.config_load",
        return_value={
            "ranking_rationale": {
                "rationale_instructions": "{{objective}}\n{{profiles_text}}",
                "response_schema": RESPONSE_SCHEMA,
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
    response_format = mock_llm.await_args.kwargs["response_format"]
    schema = response_format["json_schema"]["schema"]
    assert schema["properties"]["results"]["minItems"] == 1
    result_id = schema["properties"]["results"]["items"]["properties"]["id"]
    assert result_id["enum"] == ["urs-gubser"]


@pytest.mark.asyncio
async def test_ranking_rationale_propagates_invalid_response(mocker):
    mocker.patch(
        "skills.ranking.ranking_rationale.config_load",
        return_value={
            "ranking_rationale": {
                "rationale_instructions": "{{objective}}\n{{profiles_text}}",
                "response_schema": RESPONSE_SCHEMA,
            }
        },
    )
    mock_llm = mocker.patch(
        "skills.ranking.ranking_rationale.llm_chat",
        return_value='{"results": []}',
    )

    with pytest.raises(RuntimeError, match="failed after 3 attempts"):
        await ranking_rationale(
            [{"id": "urs-gubser", "text": "Profile", "rank": 1}],
            objective="Find experts",
        )

    assert mock_llm.await_count == 3


@pytest.mark.asyncio
async def test_ranking_rationale_does_not_retry_timeouts(mocker):
    mocker.patch(
        "skills.ranking.ranking_rationale.config_load",
        return_value={
            "ranking_rationale": {
                "rationale_instructions": "{{objective}}\n{{profiles_text}}",
                "response_schema": RESPONSE_SCHEMA,
            }
        },
    )
    mock_llm = mocker.patch(
        "skills.ranking.ranking_rationale.llm_chat",
        side_effect=TimeoutError("LLM request timed out after 180s"),
    )

    with pytest.raises(TimeoutError, match="timed out"):
        await ranking_rationale(
            [{"id": "urs-gubser", "text": "Profile", "rank": 1}],
            objective="Find experts",
        )

    assert mock_llm.await_count == 1


@pytest.mark.asyncio
async def test_ranking_rationale_retries_with_validation_feedback(mocker):
    mocker.patch(
        "skills.ranking.ranking_rationale.config_load",
        return_value={
            "ranking_rationale": {
                "rationale_instructions": "{{objective}}\n{{profiles_text}}",
                "response_schema": RESPONSE_SCHEMA,
            }
        },
    )
    mock_llm = mocker.patch(
        "skills.ranking.ranking_rationale.llm_chat",
        side_effect=[
            '{"results": []}',
            json.dumps(
                {
                    "results": [
                        {
                            "id": "urs-gubser",
                            "rationale": "Strong fit.",
                        }
                    ]
                }
            ),
        ],
    )

    result = await ranking_rationale(
        [{"id": "urs-gubser", "text": "Profile", "rank": 1}],
        objective="Find experts",
    )

    assert result[0]["rationale"] == "Strong fit."
    assert "### CORRECTION REQUIRED" not in mock_llm.await_args_list[0].args[0]
    assert "does not match the schema" in mock_llm.await_args_list[1].args[0]
