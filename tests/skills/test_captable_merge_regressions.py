"""Regression examples for the PR #61 merge review (no external services)."""
from datetime import date
from importlib import import_module
from unittest.mock import AsyncMock, Mock
import json

import pytest
from typer.testing import CliRunner

from lib.captable.model import Note, convert_in_round
from lib.captable.documents import load_parsed_documents
from lib.captable.table_extraction import _review_captable, _review_table_evidence
from lib.datasets.manifest import IngestionManifest
from lib.datasets.paths import dataset_location
from lib.datasets.source import parsed_filepath
from lib.insights import InsightFile
from lib.captable.insights import build_insight, read_build_insight, select_consolidated
from lib.storage import get_storage
from tests.skills.test_captable_analysis import _snapshot
from tests.skills.test_captable_build import _install_dataset, _patched_build, _complete_cla, _consolidated_artifact
from skills.captable.captable import build_scenarios


@pytest.mark.parametrize("discount,cap", [(0, None), (30, None), (20, 4_000_000)])
def test_dollars_invested_preserves_post_money(discount, cap):
    # Cooley's worked example: 8M pre + 2M new + 1M converting = 11M post.
    [scenario] = convert_in_round(pre_money_valuation=8_000_000,
        new_investment=2_000_000, existing_shares={"founders": 1_000_000},
        notes=[Note("note", 1_000_000, discount_pct=discount, cap=cap)],
        methods=("dollars_invested",))
    assert scenario.price_per_share * sum(scenario.shares.values()) == pytest.approx(11_000_000)
    assert scenario.ownership_pct["new_investor"] == pytest.approx(100 * 2 / 11)
    if discount == 30 and cap is None:
        assert scenario.price_per_share == pytest.approx(7.571428571)
        assert scenario.ownership_pct["founders"] == pytest.approx(68.831168831)


@pytest.mark.parametrize("currency,fx", [("CHF", {}), ("USD", {"USD": 0.5})])
def test_cap_uses_each_loans_stated_denominator(currency, fx):
    snapshot = _snapshot()
    snapshot["stakeholders"] = [
        {"name": "Founder", "kind": "individual", "role": "founder", "holdings": [{"count": 1_000_000}], "diluted_count": 1_000_000},
        {"name": "Pool", "kind": "pool", "holdings": [], "diluted_count": 1_000_000},
        {"name": "Treasury", "kind": "treasury", "holdings": [{"count": 500_000}]},
    ]
    loan = snapshot["convertibles"][0]
    loan["principal_currency"] = {"value": currency}
    prices = []
    for basis in ("issued_and_outstanding", "fully_diluted"):
        loan["denominator_basis"] = {"value": basis}
        output = build_scenarios(snapshot, pre_money=20_000_000, investment=2_000_000,
            valuation_date=date(2026, 1, 1), currency="CHF", fx_rates=fx)
        prices.append(output["scenarios"][0]["note_conversion_prices"]["lenders of cla.md"])
    factor = fx.get(currency, 1)
    assert prices == [4 * factor, 2 * factor]


def evidenced_table():
    return {"stakeholders": [{"name": "Alice", "holdings": [{"class_id": "common", "count": 100}],
        "diluted_count": 100, "quote": "Alice | 100"}],
        "totals": {"by_class": [{"class_id": "common", "issued_total": 100}], "diluted_total": 100, "quote": "Total 100"},
        "fully_diluted_definition": {"value": "full_pools", "quote": "Fully diluted includes all pools"}}


@pytest.mark.parametrize("mutation", ["owner", "amount", "definition", "missing_quote"])
def test_evidence_rejects_fabricated_rows(mutation):
    table = evidenced_table()
    reviewer = _review_captable("Alice | 100\nTotal 100\nFully diluted includes all pools")
    assert not reviewer(table).problems
    if mutation == "owner":
        table["stakeholders"][0]["name"] = "Invented Owner"
    elif mutation == "amount":
        table["stakeholders"][0]["holdings"][0]["count"] = 10
        table["totals"]["by_class"][0]["issued_total"] = 10
    elif mutation == "definition":
        table["fully_diluted_definition"]["quote"] = "Invented definition"
    else:
        del table["stakeholders"][0]["quote"]
    assert reviewer(table).problems


@pytest.mark.parametrize("rows", ["entries", "pools"])
def test_register_and_pool_evidence_is_checked(rows):
    row = {"name": "Alice", "current_common": 100, "quote": "Alice 100"} if rows == "entries" else {"label": "ESOP", "total": 100, "quote": "ESOP 100"}
    reviewer = _review_table_evidence("Alice 100\nESOP 100")
    assert not reviewer({rows: [row]}).problems
    row["quote"] = "Fabricated 100"
    assert reviewer({rows: [row]}).problems


@pytest.mark.parametrize("empty", [False, True])
def test_unparsed_documents_stop_build_coverage(mock_env, empty):
    _install_dataset("coverage", "Cap table")
    loc = dataset_location("coverage")
    get_storage().write_text(f"{loc.raw_rel}/new-loan.pdf", "source")
    if empty:
        get_storage().write_text(parsed_filepath(loc.parsed_rel, "new-loan.pdf"), " ")
    with pytest.raises(ValueError, match="new-loan.pdf"):
        load_parsed_documents("coverage")


@pytest.mark.asyncio
async def test_failed_cla_is_not_published_or_reused(mock_env, monkeypatch):
    module, _ = _patched_build(monkeypatch)
    _install_dataset("failed-co", "CLA and cap table")
    classification = {"dataset": "failed-co", "documents": [{"filename": "captable.md", "document_class": "cla_executed", "confidence": 95, "as_of_date": None, "language": "en", "rationale": "fixture"}]}
    monkeypatch.setattr(module, "classify_documents", AsyncMock(return_value=classification))
    extract = AsyncMock(side_effect=RuntimeError("temporary outage"))
    monkeypatch.setattr(module, "extract_cla", extract)
    with pytest.raises(ValueError, match="CLA extraction incomplete"):
        await module.build("failed-co")
    assert not build_insight("failed-co", "loan-extraction").exists()
    assert not get_storage().exists(f"{dataset_location('failed-co').insights_rel}/captable/latest.json")
    extract.side_effect = None
    extract.return_value = _complete_cla("failed-co", document="captable.md", status="term_sheet")
    await module.extract("failed-co")
    assert extract.await_count == 2
    assert read_build_insight(build_insight("failed-co", "loan-extraction"))["failures"] == []


@pytest.fixture
def analysis_env(mock_env, monkeypatch):
    module = import_module("skills.captable.captable")
    _install_dataset("analysis-co", "Cap table")
    location = dataset_location("analysis-co")
    manifest = IngestionManifest(get_storage(), location.parsed_rel)
    manifest.indexed_dataset_revision = "one"
    manifest.save()
    monkeypatch.setenv("RANKED_LLMS", "ollama/test_model:1b")
    snapshot = _snapshot()
    for row in snapshot["share_classes"]:
        row["quote"] = "Common shares"
    for row in snapshot["stakeholders"]:
        row.update(group=None, quote=row["name"])
    snapshot = {**_consolidated_artifact("analysis-co"), **snapshot}
    snapshot["aggregation"] = _consolidated_artifact("analysis-co")["aggregation"]
    snapshot["convertibles"] = [_complete_cla("analysis-co", **loan) for loan in snapshot["convertibles"]]
    snapshot.update(dataset="analysis-co", as_of_date="2026-06-30", generated_at="2026-09-08", tool_version="test")
    InsightFile("analysis-co", "captable_build", "manual", identifier="consolidated", subdir=True, extension="json").save(json.dumps(snapshot))
    generation = AsyncMock(return_value="Narrative")
    monkeypatch.setattr(module, "generate_markdown", generation)
    config = dict(module.load_repository_config("captable"))
    config["narrative_prompt"] = "Explain the numbers"
    monkeypatch.setattr(module, "load_repository_config", lambda *_: config)
    return module, snapshot, generation, config, manifest


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["snapshot", "prompt", "settings", "round", "revision", "date"])
async def test_analysis_reuses_and_invalidates(analysis_env, monkeypatch, change):
    module, snapshot, generate, config, manifest = analysis_env
    [first] = await module.captable("analysis-co")
    [second] = await module.captable("analysis-co")
    assert first.path == second.path
    assert generate.await_count == 1
    options = {}
    if change == "snapshot":
        snapshot["stakeholders"][0]["diluted_count"] += 1
        InsightFile("analysis-co", "captable_build", "manual", identifier="consolidated", subdir=True, extension="json").save(json.dumps(snapshot))
    elif change == "prompt": config["narrative_prompt"] += " Edited"
    elif change == "settings": config["settings"]["departed_ownership_max_pct"] = 90
    elif change == "round": options["investment"] = 3_000_000
    elif change == "revision":
        manifest.indexed_dataset_revision = "two"
        manifest.save()
    else:
        class Tomorrow(date):
            @classmethod
            def today(cls):
                return date.fromordinal(date.today().toordinal() + 1)
        monkeypatch.setattr(module, "date", Tomorrow)
    await module.captable("analysis-co", **options)
    assert generate.await_count == 2


@pytest.mark.asyncio
async def test_manual_analysis_wins_before_input_read(analysis_env, monkeypatch):
    module, _, generate, _, _ = analysis_env
    manual = InsightFile("analysis-co", "captable", "manual")
    manual.save("Human analysis")
    monkeypatch.setattr(module, "select_consolidated", Mock(side_effect=AssertionError("manual must win first")))
    [result] = await module.captable("analysis-co")
    assert result.path == manual.path
    generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_manual_build_report_precedes_even_forced_generation(mock_env, monkeypatch):
    module, _ = _patched_build(monkeypatch)
    _install_dataset("manual-co", "Cap table")
    manual = InsightFile("manual-co", "captable_build", "manual", identifier="consolidated", subdir=True, extension="json")
    manual.save(json.dumps(_consolidated_artifact("manual-co")))
    build = AsyncMock(side_effect=AssertionError("manual must win first"))
    monkeypatch.setattr(module, "_classification", build)
    [result] = await module.captable_build("manual-co", fresh=True)
    assert result.path == manual.path
    build.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_table_is_not_published_or_reused(mock_env, monkeypatch):
    module, _ = _patched_build(monkeypatch)
    table_module = import_module("lib.captable.table_extraction")
    _install_dataset("table-failure", "Cap table")
    monkeypatch.setattr(table_module, "extract_captable", AsyncMock(side_effect=RuntimeError("outage")))
    with pytest.raises(ValueError, match="Table extraction incomplete"):
        await module.build("table-failure")
    assert not build_insight("table-failure", "table-extraction").exists()
    assert not get_storage().exists(f"{dataset_location('table-failure').insights_rel}/captable/latest.json")


def test_legacy_partial_snapshot_is_not_an_input(mock_env):
    _install_dataset("partial", "Cap table")
    root = f"{dataset_location('partial').insights_rel}/captable"
    get_storage().mkdir(root)
    get_storage().write_text(f"{root}/latest.json", json.dumps({"convertible_failures": [{"document": "loan.pdf", "error": "timeout"}]}))
    with pytest.raises(ValueError, match="No consolidated"):
        select_consolidated("partial")


@pytest.mark.parametrize("package", ["captable_build", "captable", "captable_analysis"])
@pytest.mark.parametrize("flag", ["--startup", "--dataset"])
def test_canonical_and_legacy_cli_selectors(monkeypatch, package, flag):
    module = import_module(f"skills.{package}.__main__")
    run = AsyncMock(return_value=[])
    target_module = module if package == "captable_build" else import_module("skills.captable.__main__")
    monkeypatch.setattr(target_module, "captable_build" if package == "captable_build" else "captable", run)
    result = CliRunner().invoke(module.app, ["build" if package == "captable_build" else "run", flag, "example"])
    assert result.exit_code == 0, result.output
    assert run.call_args.args[0] == "example"
