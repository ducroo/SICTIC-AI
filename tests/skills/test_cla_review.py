"""cla_review: configuration contracts (slice 0) and the question-1 workflow (slice 1)."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from lib.datasets.manifest import IngestionManifest
from lib.datasets.paths import dataset_location_for_domain
from lib.infrastructure.configuration import load_repository_config
from lib.insights import InsightFile
from lib.model_config import llm_model
from lib.storage import get_storage
from skills.cla_review import cla_review as module
from skills.cla_review.cla_review import (
    APPROVED_STATUS,
    active_rules,
    cla_review,
    document_slug,
    load_reference_term_sheets,
    load_rules,
)
from tests.skills.test_captable_fixture_regressions import _term_sheet_extraction

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/captable"
GROUND_TRUTH = json.loads((FIXTURE / "ground_truth.json").read_text(encoding="utf-8"))
TERM_SHEET = (FIXTURE / "synthetic_cla_term_sheet.md").read_text(encoding="utf-8")


# --- slice 0: configuration ------------------------------------------------------

def _settings() -> dict:
    return copy.deepcopy(load_repository_config("cla_review")["settings"])


def test_every_configured_rule_is_complete_and_inactive():
    rules = load_rules(_settings())
    assert len(rules) >= 16
    assert active_rules(rules) == {}
    for name, rule in rules.items():
        assert rule["source"].strip(), name
        assert rule["status"] != APPROVED_STATUS, name


def test_only_approved_rules_may_be_active():
    settings = _settings()
    settings["rules"]["valuation_cap_required"]["active"] = True
    with pytest.raises(ValueError, match="only 'approved' rules may be active"):
        load_rules(settings)

    settings["rules"]["valuation_cap_required"]["status"] = APPROVED_STATUS
    assert set(active_rules(load_rules(settings))) == {"valuation_cap_required"}


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda s: s["rules"]["term_maximum_months"].pop("source"), "lacks"),
        (lambda s: s["rules"]["term_maximum_months"].update(status="guess"), "unknown status"),
        (lambda s: s["rules"]["term_maximum_months"].update(active="yes"), "must be a boolean"),
        (lambda s: s.update(rules={}), "non-empty"),
    ],
)
def test_malformed_rule_tables_fail_loudly(mutate, message):
    settings = _settings()
    mutate(settings)
    with pytest.raises(ValueError, match=message):
        load_rules(settings)


def test_both_seca_term_sheets_are_configured():
    references = load_reference_term_sheets(load_repository_config("cla_review"))
    assert set(references) == {
        "seca_cla_term_sheet_short_form_february_2025",
        "seca_cla_term_sheet_long_form_february_2025",
    }
    for content in references.values():
        assert "<!-- sictic-page:1 -->" in content
        assert "consents to the use, reproduction and transmission" in content
        assert "Note:" in content, "the SECA drafting notes must survive conversion"
    assert "Conditions Precedent" in references["seca_cla_term_sheet_long_form_february_2025"]


def test_reference_term_sheets_are_required():
    with pytest.raises(ValueError, match="short-form and long-form"):
        load_reference_term_sheets({"reference_term_sheets": {"only_one": "x"}})


def test_fixture_term_sheet_plants_the_recorded_absences():
    truth = GROUND_TRUTH["cla_term_sheet"]
    assert truth["status"] == "term_sheet"
    assert "(unsigned)" in TERM_SHEET
    lowered = TERM_SHEET.lower()
    for phrase in ("change of control", "most favored", "most favoured", "pro rata", "pro-rata", "floor", "fully diluted", "issued and outstanding"):
        assert phrase not in lowered, phrase
    for field in ("coc_present", "maturity_conversion_present", "denominator_basis", "mfn_clause", "pro_rata_rights", "valuation_floor"):
        assert field in truth["expected_missing_terms"], field
    for planted in ("CHF 500,000", "CHF 300,000", "Fixture Angels", "CHF 12,000,000", "discount of 20%", "two thirds", "Exclusivity", "SECA CLA Model Documentation (short form)"):
        assert planted in TERM_SHEET, planted


def test_document_identity_keeps_the_folder():
    assert document_slug("legal/drafts/CLA Term Sheet v2.pdf") == "legal-drafts-cla-term-sheet-v2-pdf"
    assert document_slug("legal/final/CLA Term Sheet v2.pdf") != document_slug("legal/drafts/CLA Term Sheet v2.pdf")
    assert document_slug("legal/a/ts.md") == "legal-a-ts"


# --- slice 1: the workflow ----------------------------------------------------------

def _install(name: str, documents: dict[str, str]) -> None:
    storage = get_storage()
    location = dataset_location_for_domain(name, "startups")
    for rel in (location.raw_rel, location.parsed_rel, location.insights_rel):
        storage.mkdir(rel)
    for path, text in documents.items():
        storage.write_text(f"{location.raw_rel}/{path}", text)
        storage.write_text(f"{location.parsed_rel}/{path}", text)
    manifest = IngestionManifest(storage, location.parsed_rel)
    manifest.indexed_dataset_revision = hashlib.sha256("".join(documents.values()).encode()).hexdigest()
    manifest.save()


def _patched(monkeypatch, *, selected: str | None = None, extraction_error: Exception | None = None) -> dict:
    calls = {"extract": 0, "identify": 0}
    monkeypatch.setenv("RANKED_LLMS", "ollama/test_model:1b")  # reusable selection ranks models

    async def fake_ensure(startup, **_kwargs):
        return SimpleNamespace(dataset_slug=startup, dataset_exists=True)

    async def fake_sync(*_args, **_kwargs):
        return None

    async def fake_extract(dataset, filename, _text):
        calls["extract"] += 1
        if extraction_error is not None:
            raise extraction_error
        return {**copy.deepcopy(_term_sheet_extraction()), "dataset": dataset, "document": filename}

    async def fake_identify(**_kwargs):
        calls["identify"] += 1
        if selected is None:
            return None
        return {
            "path": selected, "document_match": "High", "concerns": ["The draft carries no version marker."],
            "paths_for_alternative_candidates": [], "selection_reason": "Latest convertible-loan term sheet.",
        }

    monkeypatch.setattr(module, "ensure_startup_dataset", fake_ensure)
    monkeypatch.setattr(module, "sync_datasets", fake_sync)
    monkeypatch.setattr(module, "extract_cla", fake_extract)
    monkeypatch.setattr(module, "dataset_chat_json", fake_identify)
    return calls


def _intermediate(dataset: str, identifier: str) -> InsightFile:
    return InsightFile(dataset, "cla_review", llm_model(), identifier=identifier, subdir=True, extension="json")


@pytest.mark.asyncio
async def test_explicit_document_review_writes_report_and_intermediates(mock_env, monkeypatch):
    _install("acme", {"legal/a/term-sheet.md": TERM_SHEET})
    calls = _patched(monkeypatch)

    [report] = await cla_review("acme", document="legal/a/term-sheet.md", ticket=25000)

    assert calls == {"extract": 1, "identify": 0}
    assert report.filename.startswith("cla-review-acme-legal-a-term-sheet-") and report.filename.endswith(".md")
    assert "/cla-review/" not in report.path
    for stage in ("identification", "extraction", "assessment"):
        artifact = _intermediate("acme", f"legal-a-term-sheet-{stage}")
        assert artifact.exists(), stage
        assert "/cla-review/" in artifact.path
    identification = json.loads(_intermediate("acme", "legal-a-term-sheet-identification").content())
    assert identification["selection"] == "explicit" and identification["source_path"] == "legal/a/term-sheet.md"

    content = report.content()
    assert "# CLA term sheet review — acme" in content
    assert "**Selection:** explicit" in content
    assert "**Ticket:** 25,000 CHF" in content
    assert "Fixture Angels" in content
    assert "## Absent clauses" in content and "maturity_conversion_present" in content
    assert "## Company-angle assessment" in content
    assert "0 rule(s) approved and judging" in content and "open_question" in content
    assert "## Not yet covered by this report" in content
    assert "not legal advice" in content


@pytest.mark.asyncio
async def test_equal_basenames_in_different_folders_are_isolated(mock_env, monkeypatch):
    _install("acme", {"legal/a/ts.md": TERM_SHEET, "legal/b/ts.md": TERM_SHEET.replace("CHF 12,000,000", "CHF 9,000,000")})
    calls = _patched(monkeypatch)

    [first] = await cla_review("acme", document="legal/a/ts.md")
    [second] = await cla_review("acme", document="legal/b/ts.md")

    assert first.path != second.path
    assert calls["extract"] == 2
    assert _intermediate("acme", "legal-a-ts-extraction").path != _intermediate("acme", "legal-b-ts-extraction").path
    assert all(_intermediate("acme", f"legal-{folder}-ts-{stage}").exists() for folder in "ab" for stage in ("identification", "extraction", "assessment"))


@pytest.mark.asyncio
async def test_ticket_change_regenerates_the_report_but_not_the_extraction(mock_env, monkeypatch):
    _install("acme", {"legal/a/ts.md": TERM_SHEET})
    calls = _patched(monkeypatch)

    [first] = await cla_review("acme", document="legal/a/ts.md", ticket=10000)
    [second] = await cla_review("acme", document="legal/a/ts.md", ticket=20000)
    [third] = await cla_review("acme", document="legal/a/ts.md", ticket=20000)

    assert calls["extract"] == 1
    assert first.path == second.path == third.path
    assert "**Ticket:** 20,000 CHF" in third.content()


@pytest.mark.asyncio
async def test_manual_report_wins_even_when_fresh(mock_env, monkeypatch):
    _install("acme", {"legal/a/ts.md": TERM_SHEET})
    calls = _patched(monkeypatch)
    manual = InsightFile("acme", "cla_review", "manual", identifier="acme-legal-a-ts")
    manual.save("# Hand-written review\n")

    [result] = await cla_review("acme", document="legal/a/ts.md", fresh=True)

    assert result.model == "manual" and result.content() == "# Hand-written review\n"
    assert calls["extract"] == 0


@pytest.mark.asyncio
async def test_explicit_and_automatic_selection_never_share_an_identification(mock_env, monkeypatch):
    _install("acme", {"legal/a/ts.md": TERM_SHEET})
    calls = _patched(monkeypatch, selected="legal/a/ts.md")

    [automatic] = await cla_review("acme")
    [explicit] = await cla_review("acme", document="legal/a/ts.md")

    assert calls["identify"] == 1
    assert automatic.path == explicit.path  # same document, one report
    auto = json.loads(_intermediate("acme", "identification-automatic").content())
    exp = json.loads(_intermediate("acme", "legal-a-ts-identification").content())
    assert auto["selection"] == "automatic" and exp["selection"] == "explicit"
    assert auto["source_path"] == exp["source_path"] == "legal/a/ts.md"
    assert "The draft carries no version marker." in auto["concerns"]


@pytest.mark.asyncio
async def test_automatic_identification_uses_a_captable_classification_when_present(mock_env, monkeypatch):
    _install("acme", {"legal/a/ts.md": TERM_SHEET, "legal/signed.md": "# Convertible Loan Agreement (signed)"})
    calls = _patched(monkeypatch, selected="legal/a/ts.md")
    classification = InsightFile("acme", "captable_build", "manual", identifier="classification", subdir=True, extension="json")
    classification.save(json.dumps({"dataset": "acme", "documents": [
        {"filename": "legal/a/ts.md", "document_class": "cla_term_sheet", "confidence": 90, "as_of_date": "2026-07-15", "language": "en", "rationale": "draft"},
        {"filename": "legal/signed.md", "document_class": "cla_executed", "confidence": 95, "as_of_date": "2026-01-15", "language": "en", "rationale": "signed"},
    ]}))
    prompts: list[str] = []
    original = module.dataset_chat_json

    async def spy(**kwargs):
        prompts.append(kwargs["prompt"])
        return await original(**kwargs)

    monkeypatch.setattr(module, "dataset_chat_json", spy)
    await cla_review("acme")

    assert calls["identify"] == 1
    assert "never candidates): legal/signed.md" in prompts[0]
    assert "term sheets: legal/a/ts.md" in prompts[0]


@pytest.mark.asyncio
async def test_no_plausible_term_sheet_fails(mock_env, monkeypatch):
    _install("acme", {"notes.md": "Board minutes."})
    _patched(monkeypatch, selected=None)
    with pytest.raises(ValueError, match="No plausible convertible-loan term sheet"):
        await cla_review("acme")


@pytest.mark.asyncio
async def test_extraction_failure_saves_nothing(mock_env, monkeypatch):
    _install("acme", {"legal/a/ts.md": TERM_SHEET})
    _patched(monkeypatch, extraction_error=RuntimeError("model down"))
    with pytest.raises(RuntimeError, match="model down"):
        await cla_review("acme", document="legal/a/ts.md")
    assert not _intermediate("acme", "legal-a-ts-extraction").exists()
    assert not _intermediate("acme", "legal-a-ts-assessment").exists()
    assert not InsightFile("acme", "cla_review", llm_model(), identifier="acme-legal-a-ts").exists()


@pytest.mark.asyncio
async def test_unresolvable_document_path_fails(mock_env, monkeypatch):
    _install("acme", {"legal/a/ts.md": TERM_SHEET})
    _patched(monkeypatch)
    with pytest.raises(ValueError, match="Could not resolve"):
        await cla_review("acme", document="zzzz-unrelated-name.pdf")


@pytest.mark.asyncio
async def test_ticket_must_be_positive():
    with pytest.raises(ValueError, match="positive"):
        await cla_review("acme", ticket=0)
