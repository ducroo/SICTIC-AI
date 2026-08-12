from __future__ import annotations

import json
import pytest

from lib.insights import INSUFFICIENT_CONTEXT, InsightFile, strip_model_tag
from lib.insights.discovery import discover_insights
from lib.storage import get_storage
from lib.datasets.paths import dataset_location_for_domain
from lib.datasets.manifest import IngestionManifest
from lib.datasets.state import activate_dataset


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


def test_insufficient_context_helper_supports_mixed_results(mock_env):
    _create_indexed_dataset("avientus", "startups", "revision")
    insufficient = InsightFile("avientus", "startup_profile", "model-a")
    valid = InsightFile("avientus", "startup_traction", "model-a")
    insufficient.save(INSUFFICIENT_CONTEXT)
    valid.save("# Traction\n\nCustomer evidence.")

    results = [insufficient, valid]

    assert [item.has_insufficient_context() for item in results] == [True, False]


def test_strip_model_tag_recognizes_manual_insight(mock_env):
    assert strip_model_tag("persons-in-dataset-avientus-manual.md") == (
        "persons-in-dataset-avientus"
    )


def test_json_extension_uses_existing_naming_and_freshness(mock_env):
    _create_indexed_dataset("avientus", "startups", "revision")
    insight = InsightFile(
        "avientus",
        "dd_checks",
        "ollama/qwen3:8b",
        identifier="Legal Due Diligence",
        extension="json",
        config_key="structured checklist",
    )

    insight.save('{"status": "Fine"}')

    assert insight.filename == "dd-checks-legal-due-diligence-qwen3-8b.json"
    assert insight.content() == '{"status": "Fine"}'
    assert insight.is_reusable() is True


def test_find_with_any_selection_respects_json_extension(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/new-model")
    _create_indexed_dataset("avientus", "startups", "revision")
    generated = InsightFile(
        "avientus",
        "dd_checks",
        "ollama/old-model",
        identifier="Legal",
        extension="json",
        config_key="prompt",
    )
    generated.save("{}")

    requested = InsightFile(
        "avientus",
        "dd_checks",
        "ollama/new-model",
        identifier="Legal",
        extension="json",
        config_key="prompt",
    )

    assert requested.find(selection="any").path == generated.path


def test_rejects_invalid_insight_extension(mock_env):
    with pytest.raises(ValueError, match="Invalid insight extension"):
        InsightFile("avientus", "dd_checks", "model", extension="../json")


def test_find_with_reusable_selection_uses_ranked_model(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/qwen3:8b,ollama/gpt-5.4-mini")
    location = _create_indexed_dataset("avientus", "startups", "revision-1")
    generated = InsightFile(
        "avientus",
        "person_profile",
        "ollama/gpt-5.4-mini",
        identifier="Jane Doe",
        subdir=True,
        config_key="queryinstructions",
    )

    generated.save("profile")

    requested = InsightFile(
        "avientus",
        "person_profile",
        "ollama/qwen3:8b",
        identifier="Jane Doe",
        subdir=True,
        config_key="queryinstructions",
    )
    reusable = requested.find(selection="reusable")

    assert reusable is not None
    assert reusable.content() == "profile"

    manifest_path = (
        f"{location.parsed_root}/{location.slug}/insights/"
        ".insight-manifest.json"
    )
    manifest = json.loads(get_storage().read_text(manifest_path))
    assert generated.path in manifest["entries"]


def test_reusable_selection_accepts_legacy_prompt_sha256_manifest(
    mock_env,
    monkeypatch,
):
    monkeypatch.setenv("RANKED_LLMS", "ollama/qwen3:8b")
    location = _create_indexed_dataset("avientus", "startups", "revision-1")
    insight = InsightFile(
        "avientus",
        "startup_profile",
        "ollama/qwen3:8b",
        config_key="legacy configuration",
    )
    insight.save("profile")

    manifest_path = (
        f"{location.parsed_root}/{location.slug}/insights/"
        ".insight-manifest.json"
    )
    storage = get_storage()
    manifest = json.loads(storage.read_text(manifest_path))
    entry = manifest["entries"][insight.path]
    entry["prompt_sha256"] = entry.pop("config_sha256")
    storage.write_text(manifest_path, json.dumps(manifest))

    assert insight.find(selection="reusable") is not None


def test_reusable_selection_rejects_changed_dataset_or_config(
    mock_env,
    monkeypatch,
):
    monkeypatch.setenv("RANKED_LLMS", "ollama/qwen3:8b")
    location = _create_indexed_dataset("avientus", "startups", "revision-1")
    insight = InsightFile(
        "avientus",
        "startup_profile",
        "ollama/qwen3:8b",
        config_key="old configuration",
    )
    insight.save("profile")

    changed_config = InsightFile(
        "avientus",
        "startup_profile",
        "ollama/qwen3:8b",
        config_key="new configuration",
    )
    assert changed_config.find(selection="reusable") is None

    manifest = IngestionManifest.load(get_storage(), location.parsed_rel)
    manifest.indexed_dataset_revision = "revision-2"
    manifest.save()
    assert insight.find(selection="reusable") is None


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
        config_key="changed",
    )

    assert requested.find(selection="reusable").path == manual.path
    assert requested.find(selection="any").path == manual.path


def test_find_rejects_unknown_selection(mock_env):
    insight = InsightFile("avientus", "startup_profile", "manual")

    with pytest.raises(ValueError, match="Unsupported insight selection"):
        insight.find(selection="unknown")


def test_find_all_selects_one_version_for_each_logical_insight(
    mock_env,
    monkeypatch,
):
    monkeypatch.setenv(
        "RANKED_LLMS",
        "ollama/gpt-5.4-mini,ollama/qwen3:8b",
    )
    storage = get_storage()
    _create_indexed_dataset("avientus", "startups", "revision")
    storage.write_text(
        "storage/startups/avientus/insights/person-profile/"
        "jasmine-kent-gpt-5-4-mini.md",
        "generated jasmine",
    )
    storage.write_text(
        "storage/startups/avientus/insights/person-profile/"
        "jasmine-kent-manual.md",
        "manual jasmine",
    )
    storage.write_text(
        "storage/startups/avientus/insights/person-profile/"
        "urs-gubser-qwen3-8b.md",
        "generated urs",
    )
    storage.write_text(
        "storage/startups/avientus/insights/person-profile/"
        "ada-lovelace-claude-3-7.md",
        "fallback ada",
    )

    insights = InsightFile.find_all(
        skill="person_profile",
        datasets=["avientus"],
        selection="any",
    )

    assert [insight.identifier for insight in insights] == [
        "ada-lovelace",
        "jasmine-kent",
        "urs-gubser",
    ]
    assert [insight.model for insight in insights] == [
        "claude-3-7",
        "manual",
        "ollama/qwen3:8b",
    ]


def test_find_all_supports_root_insights(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/gpt-5.4-mini")
    storage = get_storage()
    _create_indexed_dataset("avientus", "startups", "revision")
    storage.write_text(
        "storage/startups/avientus/insights/"
        "startup-profile-avientus-manual.md",
        "manual startup",
    )

    insights = InsightFile.find_all(
        skill="startup_profile",
        datasets=["avientus"],
        selection="any",
    )

    assert len(insights) == 1
    assert insights[0].identifier == "avientus"
    assert insights[0].subdir is False
    assert insights[0].model == "manual"


def test_find_all_preserves_json_run_directories(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/gpt-5.4-mini")
    storage = get_storage()
    _create_indexed_dataset("avientus", "startups", "revision")
    for run_id in ("20260730T221500Z", "20260731T081500Z"):
        storage.write_text(
            "storage/startups/avientus/insights/submission-ready/"
            f"{run_id}/checklist-gpt-5-4-mini.json",
            "{}",
        )

    insights = InsightFile.find_all(
        skill="submission_ready",
        datasets=["avientus"],
        selection="any",
    )

    assert len(insights) == 2
    assert all(insight.extension == "json" for insight in insights)
    assert [insight.dataset_relative_path for insight in insights] == [
        "insights/submission-ready/20260730T221500Z/"
        "checklist-gpt-5-4-mini.json",
        "insights/submission-ready/20260731T081500Z/"
        "checklist-gpt-5-4-mini.json",
    ]


def test_find_all_keeps_same_identifier_separate_across_datasets(
    mock_env,
    monkeypatch,
):
    monkeypatch.setenv("RANKED_LLMS", "ollama/gpt-5.4-mini")
    storage = get_storage()
    for dataset in ("avientus", "novoviz"):
        _create_indexed_dataset(dataset, "startups", f"{dataset}-revision")
        activate_dataset(dataset)
        storage.write_text(
            f"storage/startups/{dataset}/insights/person-profile/"
            "jane-doe-gpt-5-4-mini.md",
            dataset,
        )

    insights = InsightFile.find_all(
        skill="person_profile",
        datasets=None,
        selection="any",
    )

    assert [(insight.dataset, insight.identifier) for insight in insights] == [
        ("avientus", "jane-doe"),
        ("novoviz", "jane-doe"),
    ]


def test_find_all_returns_empty_list_when_nothing_matches(mock_env):
    _create_indexed_dataset("avientus", "startups", "revision")

    assert InsightFile.find_all(
        skill="startup_profile",
        datasets=["avientus"],
        selection="any",
    ) == []


def test_find_all_rejects_reusable_selection(mock_env):
    with pytest.raises(
        NotImplementedError,
        match="expected source_datasets and config_key",
    ):
        InsightFile.find_all(
            skill="startup_profile",
            datasets=None,
            selection="reusable",
        )


def test_candidate_discovery_depends_only_on_skill_path(mock_env):
    storage = get_storage()
    _create_indexed_dataset("avientus", "startups", "revision")
    candidate = (
        "storage/startups/avientus/insights/person-profile/"
        "jane-doe-entirely-unknown-model.md"
    )
    storage.write_text(candidate, "profile")
    storage.write_text(
        "storage/startups/avientus/insights/investor-profile/"
        "jane-doe-manual.md",
        "investor",
    )

    candidates = discover_insights(
        "person_profile",
        datasets=["avientus"],
    )

    assert [item.path for item in candidates] == [candidate]


def test_save_prunes_missing_manifest_entries(mock_env):
    location = _create_indexed_dataset("avientus", "startups", "revision")
    first = InsightFile(
        "avientus",
        "startup_profile",
        "model-one",
        config_key="prompt",
    )
    first.save("first")
    get_storage().remove(first.path)

    second = InsightFile(
        "avientus",
        "startup_profile",
        "model-two",
        config_key="prompt",
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
        config_key="prompt",
    )

    insight.save("profile")

    assert insight.content() == "profile"
    assert insight.find(selection="reusable") is None
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
        config_key="prompt",
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
        config_key="checklist prompt",
    )
    insight.save("checklist")

    assert insight.is_reusable() is True
    changed_config = InsightFile(
        "avientus",
        "submission_ready",
        "ollama/test_model:1b",
        identifier="checklist",
        subdir=True,
        run_id="20260730T221500Z",
        config_key="changed configuration",
    )
    assert changed_config.is_reusable() is False
