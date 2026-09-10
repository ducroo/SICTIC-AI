import json
import logging

import pytest

from lib.datasets.manifest import IngestionManifest
from lib.datasets.paths import dataset_location_for_domain
from lib.insights import InsightFile
from lib.storage import get_storage


@pytest.fixture
def cached_insight(mock_env, monkeypatch, caplog):
    monkeypatch.setenv("RANKED_LLMS", "ollama/test-model")
    caplog.set_level(logging.INFO, logger="lib.insights.selection")
    manifests = {}
    for dataset, domain in [("ovomind", "startups"), ("sictic-members", "community")]:
        location = dataset_location_for_domain(dataset, domain)
        get_storage().mkdir(location.raw_rel)
        manifest = IngestionManifest(get_storage(), location.parsed_rel)
        manifest.indexed_dataset_revision = "revision-one"
        manifest.save()
        manifests[dataset] = manifest
    insight = InsightFile(
        "ovomind", "expert_search", "ollama/test-model",
        source_datasets=["ovomind", "sictic-members"],
        config_key="private prompt and contacts",
    )
    insight.save("Stored result")
    caplog.clear()
    return insight, manifests


@pytest.mark.parametrize("change,reason", [
    ("dataset", "dataset changed: sictic-members"),
    ("prompt", "prompt/configuration/inputs changed"),
    ("both", "dataset changed: sictic-members; prompt/configuration/inputs changed"),
    ("entry", "freshness metadata missing"),
    ("model", "stored model mismatch"),
    ("incomplete", "freshness metadata missing or invalid"),
    ("revision", "indexed revision missing: sictic-members"),
])
def test_cache_miss_reasons(cached_insight, caplog, change, reason):
    insight, manifests = cached_insight
    if change in {"dataset", "both", "revision"}:
        manifest = manifests["sictic-members"]
        manifest.indexed_dataset_revision = "" if change == "revision" else "revision-two"
        manifest.save()
    if change in {"prompt", "both"}:
        insight.config_key = "new private prompt and contacts"
    if change in {"entry", "model", "incomplete"}:
        metadata = insight._load_manifest()
        if change == "entry":
            metadata["entries"].pop(insight.path)
        elif change == "model":
            metadata["entries"][insight.path]["model"] = "other-model"
        else:
            metadata["entries"][insight.path].pop("config_sha256")
        get_storage().write_text(insight._manifest_path, json.dumps(metadata))

    assert insight.find(selection="reusable") is None
    messages = [record.getMessage() for record in caplog.records if record.name == "lib.insights.selection"]
    assert len(messages) == 1
    assert messages[0].startswith("[ovomind/expert_search] Cache miss")
    assert reason in messages[0]
    assert "private prompt and contacts" not in caplog.text


def test_missing_candidates(cached_insight, caplog, monkeypatch):
    insight, _ = cached_insight
    monkeypatch.setenv("RANKED_LLMS", "ollama/absent-model")
    assert insight.find(selection="reusable") is None
    assert "[ovomind/expert_search] Cache miss: no existing candidate files" in caplog.text


def test_manual_hit_precedes_revision_checks(cached_insight, caplog):
    insight, manifests = cached_insight
    manual = insight._candidate("manual")
    manual.save("Human edited")
    manifest = manifests["sictic-members"]
    manifest.indexed_dataset_revision = ""
    manifest.save()
    caplog.clear()

    assert insight.find(selection="reusable").path == manual.path
    assert "[ovomind/expert_search] Reusing manual version" in caplog.text
    assert "Cache miss" not in caplog.text


def test_rejected_model_does_not_prevent_lower_ranked_reuse(cached_insight, caplog, monkeypatch):
    insight, _ = cached_insight
    stale = InsightFile(
        "ovomind", "expert_search", "ollama/stale-model",
        source_datasets=insight.source_datasets, config_key="old prompt",
    )
    stale.save("Stale result")
    monkeypatch.setenv("RANKED_LLMS", "ollama/stale-model,ollama/test-model")
    caplog.clear()

    assert insight.find(selection="reusable").path == insight.path
    assert "Cache miss (stale-model): prompt/configuration/inputs changed" in caplog.text
    assert "Reusing generated version (test-model)" in caplog.text
    assert insight.path in caplog.text


def test_legacy_hash_reuses_without_false_miss(cached_insight, caplog):
    insight, _ = cached_insight
    metadata = insight._load_manifest()
    entry = metadata["entries"][insight.path]
    entry["prompt_sha256"] = entry.pop("config_sha256")
    get_storage().write_text(insight._manifest_path, json.dumps(metadata))

    assert insight.find(selection="reusable").path == insight.path
    assert "Reusing generated version (test-model)" in caplog.text
    assert "Cache miss" not in caplog.text


def test_reports_all_changed_dataset_names(cached_insight, caplog):
    insight, manifests = cached_insight
    for manifest in manifests.values():
        manifest.indexed_dataset_revision = "revision-two"
        manifest.save()

    assert insight.find(selection="reusable") is None
    assert "dataset changed: ovomind, sictic-members" in caplog.text
