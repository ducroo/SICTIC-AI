from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_ranking_rank_chunk_rejects_missing_ids(monkeypatch):
    import skills.ranking.ranking_top_k as ranking_top_k_mod

    monkeypatch.setattr(
        ranking_top_k_mod,
        "load_repository_config",
        lambda *sections: {
            "ranking_instructions": (
                "Objective:\n{{objective}}\n\nRank every supplied profile."
            ),
            "response_schema": {
                "type": "object",
                "properties": {
                    "ranked_profiles_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    }
                },
                "required": ["ranked_profiles_ids"],
            },
        },
    )

    async def fake_generate_json(
        prompt,
        schema,
        reviewer,
        *,
        cacheable_prompt_prefix,
    ):
        assert "fixture objective" in cacheable_prompt_prefix
        assert "Profile A" not in cacheable_prompt_prefix
        assert "Profile A" in prompt
        assert "Profile IDs: a, b" in prompt
        assert schema["properties"]["ranked_profiles_ids"]["minItems"] == 2
        assert schema["properties"]["ranked_profiles_ids"]["items"][
            "enum"
        ] == ["a", "b"]
        review = reviewer({"ranked_profiles_ids": ["b"]})
        assert review.problems == ()
        assert review.output == {"ranked_profiles_ids": ["b", "a"]}
        return review.output

    monkeypatch.setattr(
        ranking_top_k_mod,
        "generate_json",
        fake_generate_json,
    )

    result = await ranking_top_k_mod.rank_chunk(
        "fixture objective",
        {"a": "Profile A", "b": "Profile B"},
    )
    assert result == ["b", "a"]


@pytest.mark.asyncio
async def test_ranking_rank_chunk_retries_then_repairs_duplicate_ids(monkeypatch):
    import json
    from pathlib import Path

    import skills.ranking.ranking_top_k as ranking_top_k_mod

    schema = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "config/ranking_top_k/response_schema.json"
        ).read_text(encoding="utf-8")
    )
    monkeypatch.setattr(
        ranking_top_k_mod,
        "load_repository_config",
        lambda *sections: {
            "ranking_instructions": "{{objective}}\n\nRank the supplied profiles.",
            "response_schema": schema,
        },
    )

    async def duplicate_response(
        _prompt,
        _schema,
        reviewer,
        *,
        cacheable_prompt_prefix,
    ):
        assert cacheable_prompt_prefix.startswith("fixture objective")
        return reviewer({"ranked_profiles_ids": ["b", "b"]}).output

    monkeypatch.setattr(
        ranking_top_k_mod,
        "generate_json",
        duplicate_response,
    )

    result = await ranking_top_k_mod.rank_chunk(
        "fixture objective",
        {"a": "Profile A", "b": "Profile B"},
    )

    assert result == ["b", "a"]



@pytest.mark.asyncio
async def test_ranking_rank_chunk_accepts_valid_retry_after_duplicate(monkeypatch):
    import json
    from pathlib import Path

    import skills.ranking.ranking_top_k as ranking_top_k_mod

    schema = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "config/ranking_top_k/response_schema.json"
        ).read_text(encoding="utf-8")
    )
    monkeypatch.setattr(
        ranking_top_k_mod,
        "load_repository_config",
        lambda *sections: {
            "ranking_instructions": "{{objective}}\n\nRank the supplied profiles.",
            "response_schema": schema,
        },
    )
    async def retry_response(
        _prompt,
        _schema,
        reviewer,
        *,
        cacheable_prompt_prefix,
    ):
        assert cacheable_prompt_prefix.startswith("fixture objective")
        invalid = reviewer({"ranked_profiles_ids": ["x", "b"]})
        assert invalid.problems
        return {"ranked_profiles_ids": ["a", "b"]}

    monkeypatch.setattr(
        ranking_top_k_mod,
        "generate_json",
        retry_response,
    )

    result = await ranking_top_k_mod.rank_chunk(
        "fixture objective",
        {"a": "Profile A", "b": "Profile B"},
    )

    assert result == ["a", "b"]


@pytest.mark.asyncio
async def test_dealum_import_delegates_to_importer(monkeypatch):
    import skills.dealum_import.dealum_import as dealum_import_mod

    expected = SimpleNamespace(dataset_slug="example-startup")

    def fake_import_startup_from_dealum(startup):
        assert startup == "Example Startup"
        return expected

    monkeypatch.setattr(
        dealum_import_mod,
        "import_startup_from_dealum",
        fake_import_startup_from_dealum,
    )

    result = await dealum_import_mod.dealum_import("Example Startup")

    assert result is expected


def test_linkedin_maintenance_formats_unique_missing_urls():
    from skills.linkedin_maintenance.maintenance import missing_profile_urls

    result = missing_profile_urls(
        [
            {"linkedin_id": "jane-doe"},
            {"linkedin_id": "jane-doe/"},
            {"linkedin_id": ""},
            {},
        ]
    )

    assert result == ["https://www.linkedin.com/in/jane-doe/"]


def test_dataset_maintenance_filters_orphaned_qdrant_collections(skill_fixture_storage):
    from skills.dataset_maintenance.maintenance import orphaned_qdrant_collections

    class FakeAdapter:
        def list_indexed_datasets(self):
            return [
                "example-startup",
                "orphan",
            ]

    result = orphaned_qdrant_collections(adapter=FakeAdapter())

    assert result == ["orphan"]


def test_startup_website_import_validates_limits():
    from skills.startup_website_import.startup_website_import import (
        startup_website_import,
    )

    with pytest.raises(ValueError, match="depth"):
        startup_website_import("Example Startup", "https://example.com", depth=-1)


def test_standards_and_architecture_skill_is_instruction_only():
    from pathlib import Path

    path = Path("skills/standards_and_architecture/SKILL.md")

    assert path.is_file()
    assert not (path.parent / "__main__.py").exists()
    assert not (path.parent / "standards_and_architecture.py").exists()
