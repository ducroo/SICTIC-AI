"""Artifact and dependency contracts for the captable lifecycle."""
import json
from importlib import import_module
from unittest.mock import AsyncMock

import pytest

from lib.captable.insights import build_insight, read_build_insight
from lib.datasets.paths import dataset_location
from lib.insights import InsightFile
from lib.storage import get_storage
from tests.skills.test_captable_build import _install_dataset, _patched_build


@pytest.mark.asyncio
async def test_five_artifacts_and_manual_dependency_edits(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/test_model:1b")
    build, calls = _patched_build(monkeypatch)
    report = import_module("skills.captable.captable")
    generate = AsyncMock(return_value="Review the source evidence.")
    monkeypatch.setattr(report, "generate_markdown", generate)
    _install_dataset("layout-co", "Founder 900,000")
    storage = get_storage()
    root = dataset_location("layout-co").insights_rel
    legacy = f"{root}/captable/latest.json"
    storage.mkdir(f"{root}/captable")
    storage.write_text(legacy, '{"legacy": true}')

    [consolidated] = await build.captable_build("layout-co")
    [final] = await report.captable("layout-co")
    artifacts = [build_insight("layout-co", identifier) for identifier in
                 ("classification", "loan-extraction", "table-extraction", "consolidated")]
    assert all(item.exists() for item in artifacts)
    assert all(str(item.path).startswith(f"{root}/captable-build/") for item in artifacts)
    assert str(final.path).startswith(f"{root}/captable-layout-co-")
    assert str(final.path).endswith(".md")
    files = {f"{root}/{p}" for p, _ in storage.list_with_mtime(root, recursive=True)}
    outputs = {str(item.path) for item in artifacts + [final]}
    assert {p for p in files if p.endswith((".md", ".json", ".html")) and not p.rsplit('/', 1)[-1].startswith('.')} == outputs | {legacy}
    original = consolidated.content()
    await build.captable_build("layout-co")
    await report.captable("layout-co")
    assert calls == {"classify": 1, "captable": 1}
    assert generate.await_count == 1

    # A hand-edited extraction wins and invalidates consolidated data/report.
    data = read_build_insight(artifacts[2])
    manual = InsightFile("layout-co", "captable_build", "manual", identifier="table-extraction", subdir=True, extension="json")
    data["captable"]["stakeholders"][0]["name"] = "Corrected Founder"
    manual.save(json.dumps(data))
    [updated] = await build.captable_build("layout-co")
    [updated_report] = await report.captable("layout-co")
    assert updated.content() != original
    assert "Corrected Founder" in updated_report.content()
    assert calls == {"classify": 1, "captable": 1}
    assert generate.await_count == 2
    assert storage.read_text(legacy) == '{"legacy": true}'


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", ["classification", "loan-extraction", "table-extraction"])
async def test_manual_stage_preserved_on_fresh_build(mock_env, monkeypatch, identifier):
    monkeypatch.setenv("RANKED_LLMS", "ollama/test_model:1b")
    build, calls = _patched_build(monkeypatch)
    _install_dataset("manual-stage", "Founder 900,000")
    await build.captable_build("manual-stage")
    content = build_insight("manual-stage", identifier).content()
    manual = InsightFile("manual-stage", "captable_build", "manual", identifier=identifier, subdir=True, extension="json")
    manual.save(content)
    if identifier == "loan-extraction":
        monkeypatch.setattr(build, "extract_cla", AsyncMock(side_effect=AssertionError("manual must win")))
    await build.captable_build("manual-stage", fresh=True)
    assert manual.content() == content
    assert build_insight("manual-stage", identifier).find(selection="reusable").model == "manual"
    if identifier == "classification":
        assert calls["classify"] == 1
    elif identifier == "table-extraction":
        assert calls["captable"] == 1


@pytest.mark.asyncio
async def test_failed_forced_build_preserves_previous_success(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", "ollama/test_model:1b")
    build, _ = _patched_build(monkeypatch)
    _install_dataset("retry-co", "Founder 900,000")
    [previous] = await build.captable_build("retry-co")
    original = previous.content()
    table = build_insight("retry-co", "table-extraction")
    original_table = table.content()
    extraction = import_module("lib.captable.table_extraction")
    monkeypatch.setattr(extraction, "extract_captable", AsyncMock(side_effect=RuntimeError("outage")))
    with pytest.raises(ValueError, match="Table extraction incomplete"):
        await build.captable_build("retry-co", fresh=True)
    assert previous.content() == original
    assert table.content() == original_table


@pytest.mark.asyncio
async def test_manual_classification_cannot_silently_lose_missing_source(mock_env, monkeypatch):
    build, _ = _patched_build(monkeypatch)
    _install_dataset("missing-co", "Founder 900,000")
    manual = InsightFile("missing-co", "captable_build", "manual", identifier="classification", subdir=True, extension="json")
    manual.save(json.dumps({"documents": [{"filename": "absent.pdf", "document_class": "current_cap_table"}]}))
    with pytest.raises(ValueError, match="absent.pdf"):
        await build.captable_build("missing-co")
    assert not build_insight("missing-co", "consolidated").exists()
