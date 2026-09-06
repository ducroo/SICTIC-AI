from __future__ import annotations

import pytest

import skills.ranking.ranking_top_k as ranking_top_k_module


@pytest.mark.asyncio
async def test_ranking_top_k_returns_up_to_16_by_default(monkeypatch):
    async def rank_in_supplied_order(_objective, profiles):
        return list(profiles)

    monkeypatch.setattr(ranking_top_k_module, "rank_chunk", rank_in_supplied_order)
    profiles = {f"startup-{index:03d}": "Profile" for index in range(20)}

    ranked, actual_count = await ranking_top_k_module.ranking_top_k("Find fit", profiles)

    assert actual_count == len(ranked) == 16
    assert len({item["id"] for item in ranked}) == 16
    assert [item["rank"] for item in ranked] == list(range(1, 17))


@pytest.mark.asyncio
async def test_ranking_top_k_defaults_to_batches_of_16(monkeypatch):
    chunk_sizes = []

    async def rank_in_supplied_order(_objective, profiles):
        chunk_sizes.append(len(profiles))
        return list(profiles)

    monkeypatch.setattr(
        ranking_top_k_module,
        "rank_chunk",
        rank_in_supplied_order,
    )
    monkeypatch.setattr(
        ranking_top_k_module.random,
        "shuffle",
        lambda _items: None,
    )

    profiles = {f"startup-{index:03d}": "Profile" for index in range(100)}
    ranked, actual_top_k = await ranking_top_k_module.ranking_top_k(
        "Find the best fit",
        profiles,
        top_k=5,
    )

    assert actual_top_k == 5
    assert len(ranked) == 5
    assert max(chunk_sizes[:-1]) == 16
    assert all(size <= 16 for size in chunk_sizes[:-1])
    assert len(chunk_sizes) == 16


@pytest.mark.asyncio
@pytest.mark.parametrize("batch_size", [0, 1, 3, 15])
async def test_ranking_top_k_rejects_invalid_batch_size(batch_size):
    with pytest.raises(ValueError, match="batch_size"):
        await ranking_top_k_module.ranking_top_k(
            "Objective",
            {"alpha": "Profile"},
            batch_size=batch_size,
        )
