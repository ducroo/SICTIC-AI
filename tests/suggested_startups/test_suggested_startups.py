from __future__ import annotations

import pytest

from lib.insights import InsightFile
from lib.people.model import Person
from skills.suggested_startups import inputs


def test_skill_config_key_includes_shared_ranking_configuration():
    config = {
        "suggested_startups": {
            "suggested_startups_prompt": "Assess {{investor_profile}}",
        },
        "ranking_top_k": {"ranking_instructions": "rank-v1"},
        "ranking_rationale": {"rationale_instructions": "explain-v1"},
        "structured_output": {"json_response_instructions": "json-v1"},
    }

    first = inputs.load_skill_config(config)
    config["ranking_top_k"]["ranking_instructions"] = "rank-v2"
    second = inputs.load_skill_config(config)
    config["structured_output"]["json_response_instructions"] = "json-v2"
    third = inputs.load_skill_config(config)

    assert first.key != second.key
    assert second.key != third.key


def test_default_investors_preserve_canonical_people(monkeypatch):
    roster = [
        Person(full_name="Zakery Kline", linkedin_id="zakery-k-41221449"),
        Person(full_name="Agnes Petit", linkedin_id="agnes-petit-markowski"),
    ]
    monkeypatch.setattr(inputs, "persons_in_dataset", lambda _dataset: roster)

    assert inputs._resolve_investors("sictic-members", None) == roster


def test_default_investors_skip_people_without_linkedin_id(
    monkeypatch,
    caplog,
):
    roster = [
        Person(full_name="Known Person", linkedin_id="known-person"),
        Person(full_name="Incomplete Person"),
    ]
    monkeypatch.setattr(inputs, "persons_in_dataset", lambda _dataset: roster)

    assert inputs._resolve_investors("sictic-members", None) == [roster[0]]
    assert "Skipping 1 persons without a LinkedIn ID" in caplog.text


def test_requested_investor_resolves_to_canonical_person(monkeypatch):
    canonical = Person(
        full_name="Lucas du Croo de Jongh",
        linkedin_id="lucasducroodejongh",
    )
    monkeypatch.setattr(
        inputs,
        "persons_in_dataset",
        lambda _dataset: [canonical],
    )

    assert inputs._resolve_investors(
        "sictic-members",
        ["Lucas du Croo de Jongh"],
    ) == [canonical]


@pytest.mark.asyncio
async def test_load_startup_profiles_preserves_requested_order(monkeypatch):
    profiles = [
        InsightFile("beta", "startup_profile", "manual"),
        InsightFile("alpha", "startup_profile", "manual"),
    ]

    def selected(*_args, **_kwargs):
        return profiles

    monkeypatch.setattr(inputs, "select_insights", selected)

    result = await inputs.load_startup_profiles(["alpha", "beta"])

    assert [profile.dataset for profile in result] == ["alpha", "beta"]


@pytest.mark.asyncio
async def test_load_startup_profiles_rejects_missing_profile(monkeypatch):
    def selected(*_args, **_kwargs):
        return [InsightFile("alpha", "startup_profile", "manual")]

    monkeypatch.setattr(inputs, "select_insights", selected)

    with pytest.raises(
        ValueError,
        match="No stored startup profile available for: beta",
    ):
        await inputs.load_startup_profiles(["alpha", "beta"])
