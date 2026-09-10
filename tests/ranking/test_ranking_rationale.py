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
        "skills.ranking.ranking_rationale.load_repository_config",
        return_value={
            "rationale_instructions": "{{objective}}\n{{profiles_text}}",
            "response_schema": RESPONSE_SCHEMA,
        },
    )

    mock_llm = mocker.patch(
        "skills.ranking.ranking_rationale.generate_json",
        return_value={
            "results": [{"id": "urs-gubser", "rationale": "Strong fit."}]
        },
    )

    ranked_items = [{"id": "urs-gubser", "text": "Profile text", "rank": 1}]

    result = await ranking_rationale(ranked_items, objective="Find experts")

    assert result == [{"id": "urs-gubser", "text": "Profile text", "rank": 1, "rationale": "Strong fit."}]
    assert "profile_name" not in result[0]
    assert "balanced_rationale_for_ranking" not in result[0]
    schema = mock_llm.await_args.args[1]
    assert schema["properties"]["results"]["minItems"] == 1
    result_id = schema["properties"]["results"]["items"]["properties"]["id"]
    assert result_id["enum"] == ["urs-gubser"]


@pytest.mark.asyncio
async def test_ranking_rationale_propagates_invalid_response(mocker):
    mocker.patch(
        "skills.ranking.ranking_rationale.load_repository_config",
        return_value={
            "rationale_instructions": "{{objective}}\n{{profiles_text}}",
            "response_schema": RESPONSE_SCHEMA,
        },
    )
    mock_llm = mocker.patch(
        "skills.ranking.ranking_rationale.generate_json",
        side_effect=RuntimeError("generate_json failed after 3 attempts"),
    )

    with pytest.raises(RuntimeError, match="failed after 3 attempts"):
        await ranking_rationale(
            [{"id": "urs-gubser", "text": "Profile", "rank": 1}],
            objective="Find experts",
        )

    assert mock_llm.await_count == 1


@pytest.mark.asyncio
async def test_ranking_rationale_supplies_business_reviewer(mocker):
    mocker.patch(
        "skills.ranking.ranking_rationale.load_repository_config",
        return_value={
            "rationale_instructions": "{{objective}}\n{{profiles_text}}",
            "response_schema": RESPONSE_SCHEMA,
        },
    )
    mock_llm = mocker.patch(
        "skills.ranking.ranking_rationale.generate_json",
        return_value={
            "results": [
                {"id": "urs-gubser", "rationale": "Strong fit."}
            ]
        },
    )

    result = await ranking_rationale(
        [{"id": "urs-gubser", "text": "Profile", "rank": 1}],
        objective="Find experts",
    )

    assert result[0]["rationale"] == "Strong fit."
    reviewer = mock_llm.await_args.args[2]
    assert reviewer({"results": []}).problems == (
        "Missing rationale IDs: urs-gubser",
    )
