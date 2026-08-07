from __future__ import annotations

import json
import pytest

from lib.insights import InsightFile
from lib.storage import get_storage
from lib.datasets.paths import dataset_location_for_domain
from lib.datasets.manifest import IngestionManifest


def _create_indexed_dataset(name: str, domain: str, revision: str):
    storage = get_storage()
    location = dataset_location_for_domain(name, domain)
    storage.mkdir(location.raw_rel)
    manifest = IngestionManifest(storage, location.parsed_rel)
    manifest.indexed_dataset_revision = revision
    manifest.save()
    return location


def test_paths_match_existing_convention(mock_env):
    _create_indexed_dataset("daav", "startups", "revision")

    insight = InsightFile(
        "daav",
        "startup_profile",
        "ollama/gemma4:31b-nvfp4",
    )

    assert insight.directory == "storage/startups/daav/insights"
    assert insight.filename == "startup-profile-daav-gemma4-31b-nvfp4.md"
    assert insight.path == (
        "storage/startups/daav/insights/"
        "startup-profile-daav-gemma4-31b-nvfp4.md"
    )


def test_json_extension_uses_existing_naming_and_freshness(mock_env):
    _create_indexed_dataset("avientus", "startups", "revision")
    insight = InsightFile(
        "avientus",
        "dd_checks",
        "ollama/qwen3:8b",
        identifier="Legal Due Diligence",
        extension="json",
        prompt_key="structured checklist",
    )

    insight.save('{"status": "Fine"}')

    assert insight.filename == "dd-checks-legal-due-diligence-qwen3-8b.json"
    assert insight.content() == '{"status": "Fine"}'
    assert insight.is_reusable() is True


def test_find_any_respects_json_extension(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/new-model")
    _create_indexed_dataset("avientus", "startups", "revision")
    generated = InsightFile(
        "avientus",
        "dd_checks",
        "ollama/old-model",
        identifier="Legal",
        extension="json",
        prompt_key="prompt",
    )
    generated.save("{}")

    requested = InsightFile(
        "avientus",
        "dd_checks",
        "ollama/new-model",
        identifier="Legal",
        extension="json",
        prompt_key="prompt",
    )

    assert requested.find_any().path == generated.path


def test_rejects_invalid_insight_extension(mock_env):
    with pytest.raises(ValueError, match="Invalid insight extension"):
        InsightFile("avientus", "dd_checks", "model", extension="../json")


def test_save_and_find_reusable_by_ranked_model(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/qwen3:8b,ollama/gpt-5.4-mini")
    location = _create_indexed_dataset("avientus", "startups", "revision-1")
    generated = InsightFile(
        "avientus",
        "person_profile",
        "ollama/gpt-5.4-mini",
        identifier="Jane Doe",
        subdir=True,
        prompt_key="queryinstructions",
    )

    generated.save("profile")

    requested = InsightFile(
        "avientus",
        "person_profile",
        "ollama/qwen3:8b",
        identifier="Jane Doe",
        subdir=True,
        prompt_key="queryinstructions",
    )
    reusable = requested.find_reusable()

    assert reusable is not None
    assert reusable.content() == "profile"

    manifest_path = (
        f"{location.parsed_root}/{location.slug}/insights/"
        ".insight-manifest.json"
    )
    manifest = json.loads(get_storage().read_text(manifest_path))
    assert generated.path in manifest["entries"]


def test_find_reusable_rejects_changed_dataset_or_prompt(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/qwen3:8b")
    location = _create_indexed_dataset("avientus", "startups", "revision-1")
    insight = InsightFile(
        "avientus",
        "startup_profile",
        "ollama/qwen3:8b",
        prompt_key="old prompt",
    )
    insight.save("profile")

    changed_prompt = InsightFile(
        "avientus",
        "startup_profile",
        "ollama/qwen3:8b",
        prompt_key="new prompt",
    )
    assert changed_prompt.find_reusable() is None

    manifest = IngestionManifest.load(get_storage(), location.parsed_rel)
    manifest.indexed_dataset_revision = "revision-2"
    manifest.save()
    assert insight.find_reusable() is None


def test_manual_is_always_reusable_and_preferred(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/qwen3:8b")
    _create_indexed_dataset("avientus", "startups", "revision")
    manual = InsightFile(
        "avientus",
        "person_profile",
        "manual",
        identifier="Jane Doe",
        subdir=True,
    )
    manual.save("manual profile")

    requested = InsightFile(
        "avientus",
        "person_profile",
        "ollama/qwen3:8b",
        identifier="Jane Doe",
        subdir=True,
        prompt_key="changed",
    )

    assert requested.find_reusable().path == manual.path
    assert requested.find_any().path == manual.path


def test_save_prunes_missing_manifest_entries(mock_env):
    location = _create_indexed_dataset("avientus", "startups", "revision")
    first = InsightFile(
        "avientus",
        "startup_profile",
        "model-one",
        prompt_key="prompt",
    )
    first.save("first")
    get_storage().remove(first.path)

    second = InsightFile(
        "avientus",
        "startup_profile",
        "model-two",
        prompt_key="prompt",
    )
    second.save("second")

    manifest_path = (
        f"{location.parsed_root}/{location.slug}/insights/"
        ".insight-manifest.json"
    )
    entries = json.loads(get_storage().read_text(manifest_path))["entries"]
    assert first.path not in entries
    assert second.path in entries


def test_save_without_dataset_revision_keeps_output_non_reusable(mock_env):
    storage = get_storage()
    location = dataset_location_for_domain("avientus", "startups")
    storage.mkdir(location.raw_rel)
    insight = InsightFile(
        "avientus",
        "startup_profile",
        "ollama/qwen3:8b",
        prompt_key="prompt",
    )

    insight.save("profile")

    assert insight.content() == "profile"
    assert insight.find_reusable() is None
    assert not storage.exists(
        f"{location.parsed_root}/{location.slug}/insights/"
        ".insight-manifest.json"
    )


def test_save_same_content_preserves_output_mtime(mock_env):
    storage = get_storage()
    _create_indexed_dataset("avientus", "startups", "revision")
    insight = InsightFile(
        "avientus",
        "startup_profile",
        "ollama/qwen3:8b",
        prompt_key="prompt",
    )
    storage.write_text(insight.path, "profile")
    storage.set_mtime(insight.path, 123)

    insight.save("profile")

    assert storage.mtime(insight.path) == 123


def test_insight_file_supports_timestamped_run_directory(mock_env):
    _create_indexed_dataset("avientus", "startups", "revision")
    insight = InsightFile(
        "avientus",
        "submission_ready",
        "ollama/test_model:1b",
        identifier="checklist",
        subdir=True,
        run_id="20260730T221500Z",
    )

    assert insight.path == (
        "storage/startups/avientus/insights/submission-ready/"
        "20260730T221500Z/checklist-test-model-1b.md"
    )


def test_timestamped_insight_can_be_reused_for_exact_model(mock_env):
    _create_indexed_dataset("avientus", "startups", "revision")
    insight = InsightFile(
        "avientus",
        "submission_ready",
        "ollama/test_model:1b",
        identifier="checklist",
        subdir=True,
        run_id="20260730T221500Z",
        prompt_key="checklist prompt",
    )
    insight.save("checklist")

    assert insight.is_reusable() is True
    changed_prompt = InsightFile(
        "avientus",
        "submission_ready",
        "ollama/test_model:1b",
        identifier="checklist",
        subdir=True,
        run_id="20260730T221500Z",
        prompt_key="changed prompt",
    )
    assert changed_prompt.is_reusable() is False
