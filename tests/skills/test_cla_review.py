"""cla_review: configuration contracts (slice 0) and the question-1 workflow (slice 1)."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from lib.batch_audit import engine
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


def _patched(monkeypatch, *, selected: str | None = None, extraction_error: Exception | None = None,
             documentation_form: str | None = "seca_short_form", audit_status: str = "balanced", audit_error: str | None = None) -> dict:
    """Fake every model boundary; ``batch_audit`` itself runs for real on a faked check engine."""
    calls = {"extract": 0, "identify": 0, "rank": 0, "checks": 0, "synthesis": 0, "prompts": [], "prefixes": []}
    monkeypatch.setenv("RANKED_LLMS", "ollama/test_model:1b")  # reusable selection ranks models

    async def fake_ensure(startup, **_kwargs):
        return SimpleNamespace(dataset_slug=startup, dataset_exists=True)

    async def fake_sync(*_args, **_kwargs):
        return None

    async def fake_extract(dataset, filename, _text):
        calls["extract"] += 1
        if extraction_error is not None:
            raise extraction_error
        extraction = {**copy.deepcopy(_term_sheet_extraction()), "dataset": dataset, "document": filename}
        extraction["documentation_form"] = {"value": documentation_form, "quote": "based on the SECA model" if documentation_form else None}
        return extraction

    async def fake_rank(prompt, schema, reviewer=None):
        calls["rank"] += 1
        keys = schema["properties"]["rankings"]["items"]["properties"]["template_key"]["enum"]
        return {"rankings": [{"template_key": key, "rationale_for_rank": f"Fixture rank for {key}."} for key in reversed(keys)]}

    async def fake_check(**kwargs):
        calls["checks"] += 1
        calls["prefixes"].append(kwargs["cacheable_prompt_prefix"])
        if audit_error is not None:
            raise RuntimeError(audit_error)
        return {"status": audit_status, "rationale": "Fixture rationale.", "source_documents": ["legal/a/ts.md"],
                "proposed_next_steps_and_questions": [] if audit_status == "balanced" else ["Obtain the SHA."]}

    async def fake_synthesis(prompt, *_args, **_kwargs):
        calls["synthesis"] += 1
        calls["prompts"].append(prompt)
        return "### 1. Fixture finding\n\n**Finding:** synthesized from the audits."

    monkeypatch.setattr(module, "generate_json", fake_rank)
    monkeypatch.setattr(module, "generate_markdown", fake_synthesis)
    monkeypatch.setattr(engine, "dataset_chat_json", fake_check)

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

    assert (calls["extract"], calls["identify"], calls["rank"], calls["synthesis"]) == (1, 0, 0, 1)
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
    assert "## Audit against the SECA reference term sheet" in content
    assert "## Synthesis of material findings" in content and "Fixture finding" in content
    assert "Not yet covered" not in content
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


# --- slice 2: question 2 on the consolidated snapshot ---------------------------

def _executed_fixture_cla(dataset: str) -> dict:
    from tests.skills.test_captable_build import _complete_cla

    truth = GROUND_TRUTH["cla"]
    overrides = {field: {"value": truth[field], "quote": "q" if truth[field] is not None else None} for field in (
        "principal_total", "principal_currency", "interest_mode", "interest_rate_pct", "interest_day_count",
        "interest_compounding", "execution_date", "maturity_date", "valuation_cap", "discount_pct", "valuation_floor",
        "qefr_min_raise", "mfn_clause", "pro_rata_rights", "denominator_basis", "subordinated", "subordination_scope")}
    overrides["lenders"] = [{"name": l["name"], "kind": l["kind"], "domicile": l["domicile"],
                             "principal_amount": l["principal_amount"], "quote": "q"} for l in truth["lenders"]]
    return _complete_cla(dataset=dataset, document=truth["document"], status="executed", **overrides)


def _write_consolidated(dataset: str, *, model: str = "manual", broken: bool = False) -> InsightFile:
    """A valid consolidated snapshot: the smoke conftest's cap table (1,000,000 fully diluted) plus the fixture's executed CLA;
    the figures asserted below (share counts, 10/20 counts) follow from those two fixtures."""
    from tests.skill_harness.conftest import _captable_extraction
    from tests.skills.test_captable_build import _consolidated_artifact

    artifact = _consolidated_artifact(dataset, captable=_captable_extraction("captable.md"), loans=[_executed_fixture_cla(dataset)])
    if broken:
        del artifact["stakeholders"]
    insight = InsightFile(dataset, "captable_build", model, identifier="consolidated", subdir=True, extension="json")
    insight.save(json.dumps(artifact))
    return insight


@pytest.mark.asyncio
async def test_reusable_snapshot_yields_question_2(mock_env, monkeypatch):
    _install("acme", {"legal/a/ts.md": TERM_SHEET})
    _patched(monkeypatch)
    _write_consolidated("acme")

    [report] = await cla_review("acme", document="legal/a/ts.md", ticket=25000)

    content = report.content()
    assert "## Question 2 — the terms in this company" in content
    assert "Insufficient evidence" not in content
    assert "### Inputs, resolved before any number" in content
    assert "| ticket | 25,000 | explicit |" in content
    assert "Cap and discount cross at a pre-money valuation of 15,000,000" in content
    assert "| synthetic_cla.md | executed loan | Petra Muster, Bruno Muster |" in content
    assert "### 10/20 non-bank rules" in content and "After 5 members join on these terms | 6 | within | 8 | within" in content
    assert "My conversion on this cap table" not in content  # no longer pending
    conversion = json.loads(_intermediate("acme", "legal-a-ts-conversion").content())
    assert conversion["snapshot"]["state"] == "reusable" and conversion["result"]["scenarios"]
    loans = json.loads(_intermediate("acme", "legal-a-ts-loan-context").content())
    assert loans["result"]["ten_twenty"]["after"]["total_lenders_all_terms"] == 8


@pytest.mark.asyncio
async def test_absent_and_stale_snapshots_are_insufficient_evidence_not_errors(mock_env, monkeypatch):
    _install("acme", {"legal/a/ts.md": TERM_SHEET})
    _patched(monkeypatch)

    [absent] = await cla_review("acme", document="legal/a/ts.md")
    assert "**Insufficient evidence (absent cap-table snapshot).**" in absent.content()
    assert json.loads(_intermediate("acme", "legal-a-ts-conversion").content())["result"] is None

    _write_consolidated("acme", model=llm_model())  # generated, but no reusable upstream chain
    [stale] = await cla_review("acme", document="legal/a/ts.md")
    assert "**Insufficient evidence (stale cap-table snapshot).**" in stale.content()
    assert "run captable_build" in stale.content()

    _write_consolidated("acme")  # a manual snapshot wins and is reusable
    [reusable] = await cla_review("acme", document="legal/a/ts.md")
    assert "Insufficient evidence" not in reusable.content()


@pytest.mark.asyncio
async def test_malformed_snapshot_is_an_error(mock_env, monkeypatch):
    _install("acme", {"legal/a/ts.md": TERM_SHEET})
    _patched(monkeypatch)
    _write_consolidated("acme", broken=True)
    with pytest.raises(ValueError, match="stakeholders"):
        await cla_review("acme", document="legal/a/ts.md")
    assert not _intermediate("acme", "legal-a-ts-conversion").exists()


# --- slice 3: audits, reference, synthesis ---------------------------------------

def _config() -> dict:
    return load_repository_config("cla_review")


def _audit(dataset: str, docslug: str, title: str) -> InsightFile:
    return InsightFile(dataset, "batch_audit", llm_model(), identifier=f"cla_review-{docslug}-{title}", subdir=True, extension="json")


def _seeded() -> dict[str, dict[str, object]]:
    """Titles and check counts per audit group, read from the configured checklists (never hardcoded)."""
    from lib.batch_audit.checklist import parse_checklist

    config = _config()
    groups = {}
    for group, folder, _section, _placeholder in module.AUDIT_GROUPS:
        parsed = [parse_checklist(markdown) for markdown in config[folder].values()]
        groups[group] = {"titles": [c.title for c in parsed],
                         "checks": sum(len(ch.checks) for c in parsed for ch in c.chapters)}
    return groups


def test_seeded_checklists_parse_with_unique_titles_and_keywords():
    from lib.batch_audit.checklist import parse_checklist

    config = _config()
    titles = []
    for _group, folder, _section, _placeholder in module.AUDIT_GROUPS:
        assert config[folder], folder
        for key, markdown in config[folder].items():
            checklist = parse_checklist(markdown)
            titles.append(checklist.title)
            for chapter in checklist.chapters:
                for check in chapter.checks:
                    assert check.keywords, f"{key} {check.number} {check.name} has no keywords"
                    assert check.description.endswith(("?", ".")), f"{key} {check.number}"
    assert len(titles) == len(set(titles)), "audit identifiers are keyed on the checklist title"
    assert config["settings"]["checklists_provenance"]["status"] == "provisional"


def test_instruction_files_carry_their_placeholders_once():
    config = _config()
    for _group, _folder, section, placeholder in module.AUDIT_GROUPS:
        for marker in (module._TERM_SHEET_PLACEHOLDER, placeholder):
            assert config[section].count(marker) == 1, (section, marker)
        assert "not operative provisions" in config[section] or "not with a template" in config[section]
    assert config["audit_response_schema"]["properties"]["status"]["enum"] == ["unclear", "too weak", "balanced", "too strong"]
    assert "{{startup}}" in config["summary_instructions"]
    assert "`open_question`" in config["summary_instructions"] and "never a verdict" in config["summary_instructions"]


def test_documentation_forms_map_to_configured_references():
    config = _config()
    mapping = module._form_references(config, load_reference_term_sheets(config))
    assert mapping == {
        "seca_short_form": "seca_cla_term_sheet_short_form_february_2025",
        "seca_long_form": "seca_cla_term_sheet_long_form_february_2025",
    }
    with pytest.raises(ValueError, match="unknown reference"):
        module._form_references({"settings": {"documentation_form_references": {"seca_short_form": "nope"}}}, {"x": "y"})


@pytest.mark.asyncio
async def test_audits_carry_the_document_identity_and_feed_the_report(mock_env, monkeypatch):
    _install("acme", {"legal/a/ts.md": TERM_SHEET, "legal/b/ts.md": TERM_SHEET.replace("CHF 12,000,000", "CHF 9,000,000")})
    calls = _patched(monkeypatch)

    [first] = await cla_review("acme", document="legal/a/ts.md")
    checks_after_first = calls["checks"]
    [second] = await cla_review("acme", document="legal/b/ts.md")

    seeded = _seeded()
    per_document = sum(group["checks"] for group in seeded.values())
    titles = [title for group in seeded.values() for title in group["titles"]]
    assert checks_after_first == per_document and calls["checks"] == 2 * per_document
    for docslug in ("legal-a-ts", "legal-b-ts"):
        for title in titles:
            audit = _audit("acme", docslug, title)
            assert audit.exists() and "/batch-audit/" in audit.path
            assert json.loads(audit.content())["skill"] == f"cla_review-{docslug}"
    assert _audit("acme", "legal-a-ts", titles[0]).path != _audit("acme", "legal-b-ts", titles[0]).path
    content = first.content()
    assert all(f"### {title}" in content for title in titles)
    assert "## The SHA and articles: can the conversion be executed" in content
    assert "| 1.1.1 |" in content and "balanced" in content
    assert "Originating path: legal/a/ts.md" in calls["prefixes"][0]
    assert "Reference key: seca_cla_term_sheet_short_form_february_2025" in calls["prefixes"][0]
    assert second.path != first.path


@pytest.mark.asyncio
async def test_stated_documentation_form_skips_the_ranking(mock_env, monkeypatch):
    _install("acme", {"legal/a/ts.md": TERM_SHEET})
    calls = _patched(monkeypatch, documentation_form="seca_long_form")

    [report] = await cla_review("acme", document="legal/a/ts.md")

    assert calls["rank"] == 0
    reference = json.loads(_intermediate("acme", "legal-a-ts-reference").content())
    assert reference["selection"] == "stated" and reference["reference_key"] == "seca_cla_term_sheet_long_form_february_2025"
    assert reference["rankings"] == [] and "seca_long_form" in reference["reason"]
    assert "**Reference term sheet:** `seca_cla_term_sheet_long_form_february_2025` (stated:" in report.content()


@pytest.mark.asyncio
async def test_unstated_documentation_form_ranks_the_references(mock_env, monkeypatch):
    _install("acme", {"legal/a/ts.md": TERM_SHEET})
    calls = _patched(monkeypatch, documentation_form="unstated")

    await cla_review("acme", document="legal/a/ts.md")
    await cla_review("acme", document="legal/a/ts.md")

    assert calls["rank"] == 1  # the reference artifact is reused
    reference = json.loads(_intermediate("acme", "legal-a-ts-reference").content())
    assert reference["selection"] == "ranked" and len(reference["rankings"]) == 2
    assert reference["reference_key"] == reference["rankings"][0]["template_key"]
    assert "ranked by the model" in reference["reason"]


@pytest.mark.asyncio
async def test_bespoke_documentation_form_ranks_too(mock_env, monkeypatch):
    _install("acme", {"legal/a/ts.md": TERM_SHEET})
    calls = _patched(monkeypatch, documentation_form="bespoke")
    await cla_review("acme", document="legal/a/ts.md")
    assert calls["rank"] == 1


@pytest.mark.asyncio
async def test_a_failed_check_blocks_the_report(mock_env, monkeypatch):
    _install("acme", {"legal/a/ts.md": TERM_SHEET})
    calls = _patched(monkeypatch, audit_error="model down")
    with pytest.raises(ValueError, match="error"):
        await cla_review("acme", document="legal/a/ts.md")
    assert calls["synthesis"] == 0
    assert not InsightFile("acme", "cla_review", llm_model(), identifier="acme-legal-a-ts").exists()


@pytest.mark.asyncio
async def test_unclear_executability_reaches_the_report_and_the_synthesis(mock_env, monkeypatch):
    _install("acme", {"legal/a/ts.md": TERM_SHEET})
    calls = _patched(monkeypatch, audit_status="unclear")

    [report] = await cla_review("acme", document="legal/a/ts.md")

    content = report.content()
    assert "Obtain the SHA." in content
    [prompt] = calls["prompts"]
    config = _config()
    assert all(f"### EXECUTABILITY AUDIT: {key}" in prompt for key in config["executability_checklists"])
    assert all(f"### AUDIT AGAINST THE SECA REFERENCE: {key}" in prompt for key in config["checklists"])
    assert "### ASSESSMENTS (company angle, lender angle)" in prompt and '"open_question"' in prompt
    assert "### QUESTION 2 (conversion, existing loans)" in prompt and '"absent"' in prompt
    assert "never a verdict" in prompt
    assert prompt.index("CONTENT END") < prompt.index("AUTHORITATIVE SUMMARY INSTRUCTIONS")


@pytest.mark.asyncio
async def test_executability_prefix_lists_the_assumptions_and_known_constitutional_documents(mock_env, monkeypatch):
    _install("acme", {"legal/a/ts.md": TERM_SHEET, "legal/articles.md": "# Articles", "legal/sha.md": "# SHA"})
    calls = _patched(monkeypatch)
    classification = InsightFile("acme", "captable_build", "manual", identifier="classification", subdir=True, extension="json")
    classification.save(json.dumps({"dataset": "acme", "documents": [
        {"filename": "legal/a/ts.md", "document_class": "cla_term_sheet", "confidence": 90, "as_of_date": "2026-07-15", "language": "en", "rationale": "draft"},
        {"filename": "legal/articles.md", "document_class": "articles_of_association", "confidence": 95, "as_of_date": "2026-01-15", "language": "en", "rationale": "articles"},
        {"filename": "legal/sha.md", "document_class": "sha_or_priced_term_sheet", "confidence": 95, "as_of_date": "2026-01-15", "language": "en", "rationale": "sha"},
    ]}))

    await cla_review("acme", document="legal/a/ts.md")

    executability = [p for p in calls["prefixes"] if "CONVERSION ASSUMPTIONS OF THE TERM SHEET" in p]
    seeded = _seeded()
    assert len(executability) == seeded["executability"]["checks"]
    assert len(calls["prefixes"]) == seeded["executability"]["checks"] + seeded["reference"]["checks"]
    prefix = executability[0]
    assert "- conversion_capital_sources: conditional_capital, consents;" in prefix
    assert "- sha_accession_required: True;" in prefix
    assert "- denominator_basis: not stated;" in prefix
    assert "- legal/articles.md (articles_of_association)" in prefix and "- legal/sha.md (sha_or_priced_term_sheet)" in prefix
    assert "legal/a/ts.md (cla_term_sheet)" not in prefix
    assert "Reference key:" not in prefix


@pytest.mark.asyncio
async def test_fresh_regenerates_the_report_but_batch_audit_keeps_its_audits(mock_env, monkeypatch):
    _install("acme", {"legal/a/ts.md": TERM_SHEET})
    calls = _patched(monkeypatch)
    await cla_review("acme", document="legal/a/ts.md")
    checks = calls["checks"]
    [report] = await cla_review("acme", document="legal/a/ts.md", fresh=True)
    assert calls["checks"] == checks and calls["synthesis"] == 2 and report.exists()


@pytest.mark.asyncio
async def test_missing_checklist_folder_fails_loudly(mock_env, monkeypatch):
    _install("acme", {"legal/a/ts.md": TERM_SHEET})
    _patched(monkeypatch)
    real = module.load_repository_config

    def without_executability(*sections):
        config = real(*sections)
        if not sections:
            config = dict(config)
            config["cla_review"] = {k: v for k, v in config["cla_review"].items() if k != "executability_checklists"}
        return config

    monkeypatch.setattr(module, "load_repository_config", without_executability)
    with pytest.raises(ValueError, match="executability_checklists"):
        await cla_review("acme", document="legal/a/ts.md")
