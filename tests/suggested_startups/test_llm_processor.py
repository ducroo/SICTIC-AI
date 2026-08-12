from __future__ import annotations

import json
from pathlib import Path

import pytest

from skills.suggested_startups import generation, response


RESPONSE_SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "config"
        / "suggested_startups"
        / "response_schema.json"
    ).read_text(encoding="utf-8")
)

PROMPT_TEMPLATE = """
Investor: {{investor_profile}}
Startups: {{startup_profiles}}
Maximum: {{max_startups}}
Schema: {{response_schema}}
"""


@pytest.mark.asyncio
async def test_generate_report_uses_and_validates_schema(monkeypatch):
    captured = {}

    async def fake_llm_chat(*, prompt, response_format):
        captured["prompt"] = prompt
        captured["response_format"] = response_format
        return json.dumps(
            {
                "suggestions": [
                    {
                        "startup_name": "Beta SA",
                        "rank": 2,
                        "rationale": "Relevant operating experience.",
                    },
                    {
                        "startup_name": "Acme AG",
                        "rank": 1,
                        "rationale": "Strong industry alignment.",
                    },
                ]
            }
        )

    monkeypatch.setattr(generation, "llm_chat", fake_llm_chat)
    monkeypatch.setattr(
        generation,
        "dealum_url_for_startup",
        lambda startup: {
            "Acme AG": "https://app.dealum.com/#/dealroom/1?application=10",
        }.get(startup),
    )

    report = await generation.generate_report(
        "Jane Doe",
        "Investor profile",
        "Startup profiles",
        PROMPT_TEMPLATE,
        RESPONSE_SCHEMA,
        ["Acme AG", "Beta SA"],
        2,
    )

    assert (
        "| Acme AG | [Open in Dealum]"
        "(https://app.dealum.com/#/dealroom/1?application=10) | "
        "Strong industry alignment. |"
    ) in report
    assert "| Beta SA | — | Relevant operating experience. |" in report
    assert "{{response_schema}}" not in captured["prompt"]
    assert '"suggestions"' in captured["prompt"]
    assert '"enum": [' in captured["prompt"]
    assert "Maximum: 2" in captured["prompt"]
    schema = captured["response_format"]["json_schema"]["schema"]
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert schema["properties"]["suggestions"]["maxItems"] == 2
    properties = schema["properties"]["suggestions"]["items"]["properties"]
    assert properties["startup_name"]["enum"] == ["Acme AG", "Beta SA"]
    assert properties["rank"]["maximum"] == 2
    base_properties = RESPONSE_SCHEMA["properties"]["suggestions"]["items"][
        "properties"
    ]
    assert "enum" not in base_properties["startup_name"]


@pytest.mark.asyncio
async def test_generate_report_rejects_noncanonical_shape(monkeypatch):
    async def fake_llm_chat(**_kwargs):
        return '[{"startup_name":"Acme AG","rank":1,"rationale":"Fit"}]'

    monkeypatch.setattr(generation, "llm_chat", fake_llm_chat)

    with pytest.raises(
        ValueError,
        match=r"Invalid suggested-startups response for Jane Doe:.*schema",
    ):
        await generation.generate_report(
            "Jane Doe",
            "Investor profile",
            "Startup profiles",
            PROMPT_TEMPLATE,
            RESPONSE_SCHEMA,
            ["Acme AG"],
            1,
        )


@pytest.mark.asyncio
async def test_generate_report_rejects_startup_alias(monkeypatch):
    async def fake_llm_chat(**_kwargs):
        return json.dumps(
            {
                "suggestions": [
                    {
                        "startup_name": "DAAV SA",
                        "rank": 1,
                        "rationale": "Fit",
                    }
                ]
            }
        )

    monkeypatch.setattr(generation, "llm_chat", fake_llm_chat)

    with pytest.raises(
        ValueError,
        match=r"Invalid suggested-startups response for Jane Doe:.*schema",
    ):
        await generation.generate_report(
            "Jane Doe",
            "Investor profile",
            "Startup profiles",
            PROMPT_TEMPLATE,
            RESPONSE_SCHEMA,
            ["daav"],
            1,
        )


@pytest.mark.parametrize(
    ("suggestions", "candidates", "maximum", "message"),
    [
        (
            [{"startup_name": "Imaginary AI", "rank": 1, "rationale": "Fit"}],
            ["Acme AG"],
            1,
            "Unknown suggested startup",
        ),
        (
            [
                {"startup_name": "Acme AG", "rank": 1, "rationale": "Fit"},
                {"startup_name": "Beta SA", "rank": 1, "rationale": "Fit"},
            ],
            ["Acme AG", "Beta SA"],
            2,
            "ranks must be unique and sequential",
        ),
        (
            [
                {"startup_name": "Acme AG", "rank": 1, "rationale": "Fit"},
                {"startup_name": "Beta SA", "rank": 2, "rationale": "Fit"},
            ],
            ["Acme AG", "Beta SA"],
            1,
            "maximum is 1",
        ),
        (
            [{"startup_name": "Acme AG", "rank": 1, "rationale": "   "}],
            ["Acme AG"],
            1,
            "empty rationale",
        ),
    ],
)
def test_business_validation_rejects_invalid_rankings(
    suggestions,
    candidates,
    maximum,
    message,
):
    with pytest.raises(ValueError, match=message):
        response._validate_business_rules(suggestions, candidates, maximum)
