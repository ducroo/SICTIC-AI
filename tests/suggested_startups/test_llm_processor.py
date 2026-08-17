from __future__ import annotations

from types import SimpleNamespace

import pytest

from skills.suggested_startups import generation


def test_compile_startup_profiles_returns_id_to_content_mapping():
    profiles = [
        SimpleNamespace(dataset="alpha", content=lambda: "Alpha profile"),
        SimpleNamespace(dataset="beta", content=lambda: "Beta profile"),
    ]

    assert generation.compile_startup_profiles(profiles) == {
        "alpha": "Alpha profile",
        "beta": "Beta profile",
    }


def test_compile_startup_profiles_rejects_duplicate_ids():
    profiles = [
        SimpleNamespace(dataset="alpha", content=lambda: "First"),
        SimpleNamespace(dataset="alpha", content=lambda: "Second"),
    ]

    with pytest.raises(ValueError, match="Duplicate startup profile ID"):
        generation.compile_startup_profiles(profiles)


@pytest.mark.asyncio
async def test_generate_report_uses_shared_ranker_default_batch_size(
    monkeypatch,
):
    captured = {}

    async def fake_ranking_top_k(**kwargs):
        captured["ranking"] = kwargs
        return (
            [
                {"id": "alpha", "text": "Alpha profile", "rank": 1},
                {"id": "beta", "text": "Beta profile", "rank": 2},
            ],
            2,
        )

    async def fake_ranking_rationale(**kwargs):
        captured["rationale"] = kwargs
        return [
            {
                **item,
                "rationale": f"Rationale for {item['id']}.",
            }
            for item in kwargs["ranked_items"]
        ]

    monkeypatch.setattr(generation, "ranking_top_k", fake_ranking_top_k)
    monkeypatch.setattr(
        generation,
        "ranking_rationale",
        fake_ranking_rationale,
    )
    monkeypatch.setattr(
        generation,
        "dealum_url_for_startup",
        lambda startup: "https://dealum.test/alpha"
        if startup == "alpha"
        else None,
    )

    report = await generation.generate_report(
        "Jane Doe",
        "Investor profile",
        {"alpha": "Alpha profile", "beta": "Beta profile"},
        "Assess fit for {{investor_profile}}",
        2,
    )

    assert captured["ranking"] == {
        "objective": (
            "Assess fit for === INVESTOR PROFILE: Jane Doe ===\n"
            "Investor profile"
        ),
        "all_profiles": {
            "alpha": "Alpha profile",
            "beta": "Beta profile",
        },
        "top_k": 2,
    }
    assert "batch_size" not in captured["ranking"]
    assert captured["rationale"]["objective"] == captured["ranking"][
        "objective"
    ]
    assert (
        "| alpha | [Open in Dealum](https://dealum.test/alpha) | "
        "Rationale for alpha. |"
    ) in report
    assert "| beta | — | Rationale for beta. |" in report


@pytest.mark.asyncio
async def test_generate_report_propagates_ranking_failure(monkeypatch):
    async def failing_ranking(**_kwargs):
        raise ValueError("invalid chunk ranking")

    monkeypatch.setattr(generation, "ranking_top_k", failing_ranking)

    with pytest.raises(ValueError, match="invalid chunk ranking"):
        await generation.generate_report(
            "Jane Doe",
            "Investor profile",
            {"alpha": "Alpha profile"},
            "Assess fit for {{investor_profile}}",
            1,
        )
