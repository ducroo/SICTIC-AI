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
from lib.storage import get_storage
from tests.skills.test_captable_analysis import _snapshot
from tests.skills.test_captable_build import _install_dataset, _patched_build
from skills.captable_analysis.captable_analysis import build_scenarios


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
    classification = {"documents": [{"filename": "captable.md", "document_class": "cla_executed"}]}
    monkeypatch.setattr(module, "classify_documents", AsyncMock(return_value=classification))
    extract = AsyncMock(side_effect=RuntimeError("temporary outage"))
    monkeypatch.setattr(module, "extract_cla", extract)
    with pytest.raises(ValueError, match="CLA extraction incomplete"):
        await module.build("failed-co")
    assert module._load_work("failed-co", "cla_extraction.json") is None
    assert not get_storage().exists(f"{dataset_location('failed-co').insights_rel}/captable/latest.json")
    extract.side_effect = None
    extract.return_value = {"document": "captable.md", "status": "term_sheet", "lenders": []}
    await module.extract("failed-co")
    assert extract.await_count == 2
    assert module._load_work("failed-co", "cla_extraction.json")["failures"] == []


@pytest.fixture
def analysis_env(mock_env, monkeypatch):
    module = import_module("skills.captable_analysis.captable_analysis")
    _install_dataset("analysis-co", "Cap table")
    location = dataset_location("analysis-co")
    manifest = IngestionManifest(get_storage(), location.parsed_rel)
    manifest.indexed_dataset_revision = "one"
    manifest.save()
    monkeypatch.setenv("RANKED_LLMS", "ollama/test_model:1b")
    snapshot = _snapshot()
    monkeypatch.setattr(module, "_load_snapshot", Mock(return_value=snapshot))
    generation = AsyncMock(return_value="Narrative")
    monkeypatch.setattr(module, "generate_markdown", generation)
    config = {"narrative_prompt": "Explain the numbers"}
    monkeypatch.setattr(module, "load_repository_config", lambda *_: config)
    return module, snapshot, generation, config, manifest


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["snapshot", "prompt", "round", "revision", "date"])
async def test_analysis_reuses_and_invalidates(analysis_env, monkeypatch, change):
    module, snapshot, generate, config, manifest = analysis_env
    [first] = await module.captable_analysis("analysis-co")
    [second] = await module.captable_analysis("analysis-co")
    assert first.path == second.path
    assert generate.await_count == 1
    options = {}
    if change == "snapshot": snapshot["stakeholders"][0]["diluted_count"] += 1
    elif change == "prompt": config["narrative_prompt"] += " Edited"
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
    await module.captable_analysis("analysis-co", **options)
    assert generate.await_count == 2


@pytest.mark.asyncio
async def test_manual_analysis_wins_before_snapshot_read(analysis_env):
    module, _, generate, _, _ = analysis_env
    manual = InsightFile("analysis-co", "captable_analysis", "manual")
    manual.save("Human analysis")
    module._load_snapshot.side_effect = AssertionError("manual must win first")
    [result] = await module.captable_analysis("analysis-co")
    assert result.path == manual.path
    generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_manual_build_report_precedes_even_forced_generation(mock_env, monkeypatch):
    module, _ = _patched_build(monkeypatch)
    _install_dataset("manual-co", "Cap table")
    manual = InsightFile("manual-co", "captable_build", "manual")
    manual.save("Human cap table report")
    build = AsyncMock(side_effect=AssertionError("manual must win first"))
    monkeypatch.setattr(module, "build", build)
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
    assert module._load_work("table-failure", "table_extraction.json") is None
    assert not get_storage().exists(f"{dataset_location('table-failure').insights_rel}/captable/latest.json")


def test_legacy_partial_snapshot_is_rejected(mock_env):
    module = import_module("skills.captable_analysis.captable_analysis")
    _install_dataset("partial", "Cap table")
    root = f"{dataset_location('partial').insights_rel}/captable"
    get_storage().mkdir(root)
    get_storage().write_text(f"{root}/latest.json", json.dumps({"convertible_failures": [{"document": "loan.pdf", "error": "timeout"}]}))
    with pytest.raises(ValueError, match="failed CLA"):
        module._load_snapshot("partial", None)


@pytest.mark.parametrize("package", ["captable_build", "captable_analysis"])
@pytest.mark.parametrize("flag", ["--startup", "--dataset"])
def test_canonical_and_legacy_cli_selectors(monkeypatch, package, flag):
    module = import_module(f"skills.{package}.__main__")
    run = AsyncMock(return_value={"computed": {}, "narrative": "ok"} if package == "captable_analysis" else [])
    target = "analyze" if package == "captable_analysis" else "captable_build"
    monkeypatch.setattr(module, target, run)
    result = CliRunner().invoke(module.app, ["run" if package == "captable_analysis" else "build", flag, "example"])
    assert result.exit_code == 0, result.output
    assert run.call_args.args[0] == "example"
