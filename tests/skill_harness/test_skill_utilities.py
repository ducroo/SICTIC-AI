from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_llm_chat_uses_gateway_without_live_model(monkeypatch):
    from skills.llm_chat.llm_chat import llm_chat
    import skills.llm_chat.llm_chat as llm_chat_mod

    captured = {}

    async def fake_completion(kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="fixture completion")
                )
            ]
        )

    monkeypatch.setattr(llm_chat_mod.gateway, "request_completion", fake_completion)

    result = await llm_chat("Summarize the fixture.")

    assert result == "fixture completion"
    assert captured["messages"][0]["content"] == "Summarize the fixture."
    assert captured["num_ctx"] == 4096


@pytest.mark.asyncio
async def test_ranking_rank_chunk_rejects_missing_ids(monkeypatch):
    import skills.ranking.ranking_top_k as ranking_top_k_mod

    monkeypatch.setattr(
        ranking_top_k_mod,
        "config_load",
        lambda: {
            "ranking_top_k": {
                "ranking_instructions": (
                    "{{objective}}\n{{profiles_text}}\n{{n_profiles}}\n{{IDs_profiles}}"
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
            }
        },
    )

    async def fake_llm_chat(*_args, **_kwargs):
        schema = _kwargs["response_format"]["json_schema"]["schema"]
        assert schema["properties"]["ranked_profiles_ids"]["minItems"] == 2
        assert schema["properties"]["ranked_profiles_ids"]["items"][
            "enum"
        ] == ["a", "b"]
        return '{"ranked_profiles_ids": ["b"]}'

    monkeypatch.setattr(ranking_top_k_mod, "llm_chat", fake_llm_chat)

    result = await ranking_top_k_mod.rank_chunk(
        "fixture objective",
        {"a": "Profile A", "b": "Profile B"},
    )

    assert result == ["a", "b"]


@pytest.mark.asyncio
async def test_ranking_rank_chunk_rejects_duplicate_ids(monkeypatch):
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
        "config_load",
        lambda: {
            "ranking_top_k": {
                "ranking_instructions": "{{response_schema}}",
                "response_schema": schema,
            }
        },
    )

    async def duplicate_response(*_args, **_kwargs):
        return '{"ranked_profiles_ids":["b","b"]}'

    monkeypatch.setattr(
        ranking_top_k_mod,
        "llm_chat",
        duplicate_response,
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

    class FakeAdmin:
        def list_collections(self):
            return [
                "example-startup-test-embedding-8b",
                "orphan-test-embedding-8b",
                "unrelated-other-model",
            ]

    result = orphaned_qdrant_collections(admin=FakeAdmin())

    assert result == ["orphan-test-embedding-8b"]


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
    assert "Data Storage Layout" in path.read_text(encoding="utf-8")
