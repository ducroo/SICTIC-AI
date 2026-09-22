"""Model-free regression suite over the synthetic fixture data room.

Every quirk planted in tests/fixtures/captable/ (see its README and the
``coverage`` map of ground_truth.json) has a faithful extraction the
evidence reviewer must accept and a classic mistake it must reject, and the
validators must reach the expected end state over those extractions. A
live build on the configured model is the other half of the regression;
this half never drifts with the model.
"""
import json
from pathlib import Path

import pytest

from lib.captable.table_extraction import _review_captable, _review_table_evidence
from lib.captable.validate import check_cross_snapshot, validate_captable
from lib.datasets.source import IGNORED_EXTENSIONS
from tests.skills.test_captable_build import _BUILT, _reviewer as cla_reviewer

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "captable"
GROUND_TRUTH = json.loads((FIXTURES / "ground_truth.json").read_text(encoding="utf-8"))


def text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def line(name: str, needle: str) -> str:
    return next(item for item in text(name).splitlines() if needle in item)


def problems(name: str, output: dict, *, captable: bool = False) -> list[str]:
    reviewer = _review_captable if captable else _review_table_evidence
    return list(reviewer(text(name))(output).problems)


# --- share register (German OCR-style Aktienbuch) --------------------------

ANNA = line("synthetic_register.md", "Anna Barbara Beispiel") + "\n" + line("synthetic_register.md", "150 ' 000")
BRUNO = line("synthetic_register.md", "Bruno Muster, Zug")
ALPINA = line("synthetic_register.md", "Alpina Ventures AG")
TREASURY = line("synthetic_register.md", "eigene Aktien")


def register_entries() -> list[dict]:
    quotes = [ANNA, BRUNO, ALPINA, TREASURY]
    entries = []
    for expected, quote in zip(GROUND_TRUTH["register"]["entries"], quotes):
        fields = ("current_common", "current_preferred", "current_participation_pct",
                  "first_acquisition_date", "last_change_date")
        entries.append({"name": expected["name"], **{f: expected[f] for f in fields}, "quote": quote})
    return entries


def test_register_faithful_extraction_is_accepted():
    output = {"entries": register_entries(),
              "as_of_date": {"value": "2026-03-31", "quote": "Stand per 31. März 2026"}}
    assert not problems("synthetic_register.md", output)


@pytest.mark.parametrize("index, changes, expected", [
    (0, {"current_common": 250000}, "sum to 400000"),                       # subset of the certificate rows
    (0, {"current_common": 150000, "current_preferred": None, "quote": ANNA.splitlines()[1]}, "30.77"),  # continuation row alone
    (1, {"current_preferred": 0}, "null, never 0"),                          # blank cell
    (2, {"current_common": 0}, "null, never 0"),                             # 'n/a' cell
    (3, {"current_common": 1005}, "100000"),                                 # digits joined across cells
    (3, {"current_common": 100}, "100000"),                                  # stray space read as two numbers
    (0, {"current_common": 700000, "quote": ANNA + "\n" + BRUNO}, "was ignored"),  # another holder's row
    (0, {"current_common": 300000, "quote": BRUNO}, "not named"),            # whole-document name matching
    (0, {"current_common": 400000, "quote": "| 1 | Anna Barbara Beispiel, Zürich | 1 | 400'000 |"}, "closest source line"),
])
def test_register_classic_mistakes_are_rejected(index, changes, expected):
    entries = register_entries()
    entries[index].update(changes)
    found = problems("synthetic_register.md", {"entries": entries})
    assert found and expected in found[0], found


def test_register_stacked_history_states_both_figures_and_tolerates_a_real_pipe():
    entries = register_entries()
    entries[1]["current_common"] = 200000       # stated, though not current: reconciliation catches it
    assert not problems("synthetic_register.md", {"entries": entries})
    entries = register_entries()
    entries[1]["quote"] = BRUNO.replace("&#124;", "|")
    assert not problems("synthetic_register.md", {"entries": entries})
    entries[0]["quote"] = line("synthetic_register.md", "| Nr |") + "\n" + ANNA   # header may be quoted too
    assert not problems("synthetic_register.md", {"entries": entries})


# --- pool overview (sheet export) and plan (prose) ---------------------------

SECTION = line("synthetic_pool_overview.md", "ESOP (authorized capital)")
POOL_SIZE = line("synthetic_pool_overview.md", "Pool size")
GRANTED = line("synthetic_pool_overview.md", "Granted")
SHEET_POOL = {"kind": "esop", "label": "ESOP (authorized capital)", "total": 25000, "granted": 0,
              "unallocated": 25000, "quote": "\n".join([SECTION, POOL_SIZE, GRANTED])}


def test_pool_sheet_faithful_extraction_is_accepted():
    output = {"pools": [SHEET_POOL], "as_of_date": {"value": "2026-03-31", "quote": "as of 31 March 2026"}}
    assert not problems("synthetic_pool_overview.md", output)
    assert not problems("synthetic_pool_overview.md", {"pools": [{**SHEET_POOL, "label": "ESOP"}]})
    assert not problems("synthetic_pool_overview.md", {"pools": [{**SHEET_POOL, "quote": POOL_SIZE + "\n" + GRANTED}]})
    derived = {**SHEET_POOL, "granted": None, "quote": SECTION + "\n" + POOL_SIZE}
    assert not problems("synthetic_pool_overview.md", {"pools": [derived]})
    empty_header = line("synthetic_pool_overview.md", "| | | | |")
    assert not problems("synthetic_pool_overview.md", {"pools": [{**SHEET_POOL, "quote": empty_header + "\n" + SHEET_POOL["quote"]}]})


@pytest.mark.parametrize("changes, expected", [
    ({"label": "PSOP 2024"}, "not named"),
    ({"total": 1300000, "quote": SECTION + "\n" + POOL_SIZE}, "25000"),    # the label's number is not quoted
    ({"granted": 5000}, "not evidenced"),
])
def test_pool_sheet_classic_mistakes_are_rejected(changes, expected):
    found = problems("synthetic_pool_overview.md", {"pools": [{**SHEET_POOL, **changes}]})
    assert found and expected in found[0], found


BULLETS = ("- Pool size: 25,000 options in total may be granted under the Plan, backed by the "
           "authorized capital resolved by the general meeting of 30 January 2026.\n"
           "- Granted as at the Date: 0 options; 25,000 options remain available for grant.")
PLAN_POOL = {"kind": "esop", "label": "Employee Stock Option Plan 2026", "total": 25000, "granted": 0,
             "unallocated": 25000, "quote": BULLETS}


def test_plan_pool_named_by_its_heading_and_quoted_from_a_wrapped_list():
    output = {"pools": [PLAN_POOL], "as_of_date": {"value": "2026-02-15", "quote": "Date: 15 February 2026"}}
    assert not problems("synthetic_esop_plan.md", output)
    assert not problems("synthetic_esop_plan.md", {"pools": [{**PLAN_POOL, "label": "ESOP 2026"}]})
    lines = text("synthetic_esop_plan.md").splitlines()
    start = next(i for i, item in enumerate(lines) if item.startswith("- Pool size"))
    wrapped = "\n".join(lines[start:start + 3])   # the wrapped bullet and the next one, verbatim
    assert not problems("synthetic_esop_plan.md", {"pools": [{**PLAN_POOL, "quote": wrapped}]})
    assert problems("synthetic_esop_plan.md", {"pools": [{**PLAN_POOL, "label": "Phantom Stock Plan"}]})
    assert problems("synthetic_esop_plan.md", {"pools": [{**PLAN_POOL, "total": 30000}]})
    output["as_of_date"]["quote"] = "Date: 15 March 2026"
    assert problems("synthetic_esop_plan.md", output)


# --- cap table v2 share classes ----------------------------------------------

def test_v2_share_classes_have_real_source_rows():
    classes = [
        {"id": item["id"], "name": item["name"], "nominal_value": item["nominal_value"],
         "votes_per_share": item["votes_per_share"], "quote": line("synthetic_captable_v2.md", f"| {item['name']} |")}
        for item in GROUND_TRUTH["captable_v2"]["share_classes"]
    ]
    assert not problems("synthetic_captable_v2.md", {"share_classes": classes}, captable=True)
    classes[0]["votes_per_share"] = 3
    assert problems("synthetic_captable_v2.md", {"share_classes": classes}, captable=True)
    header_only = {"id": "common", "name": "Common", "nominal_value": None, "votes_per_share": None,
                   "quote": line("synthetic_captable.md", "| Group |")}
    assert not problems("synthetic_captable.md", {"share_classes": [header_only]}, captable=True)


# --- CLA: two lenders, and the borrower is not one of them --------------------

def test_cla_borrower_in_the_party_block_is_not_a_lender():
    lenders = [
        {"name": lender["name"], "kind": "individual", "domicile": "CH",
         "principal_amount": lender["principal_amount"],
         "quote": f'**{lender["name"]}**'}
        for lender in GROUND_TRUTH["cla"]["lenders"]
    ]
    output = {"borrower_name": {"value": "Fixture Robotics AG", "quote": "**Fixture Robotics AG**"},
              "lenders": lenders}
    assert not cla_reviewer(text("synthetic_cla.md"))(output).problems
    output["lenders"].append({"name": "Fixture Robotics AG", "kind": "entity", "domicile": "CH",
                              "principal_amount": None, "quote": "**Fixture Robotics AG**"})
    found = cla_reviewer(text("synthetic_cla.md"))(output).problems
    assert found and "this is the borrower" in found[0]


# --- the planted quirks must stay in the documents ---------------------------

@pytest.mark.parametrize("name, needle", [
    ("synthetic_register.md", "&#124;"),
    ("synthetic_register.md", "| 3 | 200'000 300'000 | | 15.38% 23.08% |"),
    ("synthetic_register.md", "| | | 2 | 150 ' 000 |"),
    ("synthetic_register.md", "| n/a | 500 ' 000 |"),
    ("synthetic_register.md", "| 100 000 | - |"),
    ("synthetic_register.md", "| # |"),
    ("synthetic_register.md", "Seite 2\n\n| | | 2 | 150 ' 000 |"),
    ("synthetic_pool_overview.md", "| | | | |\n| --- |"),
    ("synthetic_pool_overview.md", "| Pool size (options) | 25000 | # |"),
    ("synthetic_pool_overview.md", "% of shares issued (1,300,000)"),
    ("synthetic_esop_plan.md", "Date:\n\n15 February 2026"),
    ("synthetic_cla.md", "Lender 2 contributes CHF 50,000.00"),
    ("synthetic_cla_term_sheet.md", "*(unsigned)*"),
    ("synthetic_cla_term_sheet.md", "Only the sections marked \"Binding\""),
])
def test_planted_quirks_are_still_in_the_documents(name, needle):
    assert needle in text(name)


def test_page_three_marker_sits_between_two_table_rows():
    lines = text("synthetic_register.md").splitlines()
    marker = lines.index("<!-- sictic-page:3 -->")
    before = next(item for item in reversed(lines[:marker]) if item.strip())
    after = next(item for item in lines[marker + 1:] if item.strip())
    assert before.startswith("| 3 | Alpina") and after.startswith("| 4 | Fixture")


def test_page_two_opens_with_a_running_header_and_a_nameless_continuation_row():
    lines = text("synthetic_register.md").splitlines()
    marker = lines.index("<!-- sictic-page:2 -->")
    following = [item for item in lines[marker + 1:] if item.strip()][:3]
    assert following[0].startswith("Aktienbuch der Fixture Robotics AG")
    assert following[1].startswith("| | | 2 | 150 ' 000 |") and following[2].startswith("| ---")
    entries = register_entries()
    entries[1].update({"current_common": 450000, "quote": ANNA.splitlines()[1] + "\n" + BRUNO})
    found = problems("synthetic_register.md", {"entries": entries})
    assert found and "was ignored" in found[0]          # the continuation row is Anna's, not Bruno's
    entries = register_entries()
    entries[0].update({"current_common": 2, "quote": ANNA.splitlines()[1]})
    assert problems("synthetic_register.md", {"entries": entries})   # inherited header: Zertifikat is not a count


def test_decoy_design_asset_is_ignored_by_ingestion():
    assert (FIXTURES / "fixture_logo.ai").is_file()
    assert "fixture_logo.ai".endswith(IGNORED_EXTENSIONS)


# --- expected end state of a build over the faithful extractions -------------

def holder(name, kind, role, holdings, diluted, invested=0):
    return {"name": name, "group": None, "kind": kind, "role": role,
            "holdings": [{"class_id": c, "count": n} for c, n in holdings], "diluted_count": diluted,
            "invested_amount": invested, "quote": name}


def captable(as_of, holders, pool_total, common, preferred, diluted):
    return {
        "as_of_date": {"value": as_of, "quote": as_of},
        "share_classes": [{"id": "common", "name": "Common", "nominal_value": 0.1, "votes_per_share": 1, "quote": "Common"},
                          {"id": "preferred_a", "name": "Preferred A", "nominal_value": 0.1, "votes_per_share": 1, "quote": "Preferred A"}],
        "stakeholders": holders,
        "pools": [{"kind": "grantable", "label": "Equity plans grantable", "total": pool_total, "granted": None,
                   "unallocated": pool_total, "quote": "Equity plans grantable"}],
        "totals": {"by_class": [{"class_id": "common", "issued_total": common}, {"class_id": "preferred_a", "issued_total": preferred}],
                   "diluted_total": diluted, "quote": "Total"},
    }


MARCH = captable("2026-03-31", [
    holder("Anna Beispiel", "individual", "founder", [("common", 400000)], 400000),
    holder("Bruno Muster", "individual", "founder", [("common", 300000)], 340000),
    holder("Alpina Ventures AG", "entity", "investor", [("preferred_a", 500000)], 500000, 1000000),
    holder("Carla Test", "individual", "employee", [], 10000),
    holder("Authorized Capital", "authorized_capital", "pool", [], 25000),
    holder("Fixture Robotics AG Treasury", "treasury", "company", [("common", 100000)], None),
], 25000, 800000, 500000, 1275000)

JUNE = captable("2026-06-30", [
    holder("Anna Beispiel", "individual", "founder", [("common", 400000)], 400000),
    holder("Bruno Muster", "individual", "founder", [("common", 250000)], 290000),
    holder("Alpina Ventures AG", "entity", "investor", [("preferred_a", 500000)], 500000, 1000000),
    holder("Helvetia Growth AG", "entity", "investor", [("preferred_a", 100000)], 100000, 450000),
    holder("Carla Test", "individual", "employee", [], 10000),
    holder("Diego Probe", "individual", "employee", [], 15000),
    holder("Authorized Capital", "authorized_capital", "pool", [], 10000),
    holder("Fixture Robotics AG Treasury", "treasury", "company", [("common", 100000)], None),
    holder("Emil Weg", "individual", "departed", [("common", 50000)], 50000),
], 10000, 800000, 600000, 1375000)


def test_ground_truth_end_state_over_the_faithful_extractions():
    truth = GROUND_TRUTH
    assert MARCH["totals"]["diluted_total"] == truth["captable"]["totals"]["diluted_total"]
    assert JUNE["totals"]["diluted_total"] == truth["captable_v2"]["totals"]["diluted_total"]
    register = {"document": "synthetic_register.md", "as_of_date": {"value": "2026-03-31", "quote": ""},
                "entries": register_entries()}
    pool_docs = [
        {"document": pool["document"], "as_of_date": {"value": pool["as_of_date"], "quote": ""},
         "pools": [{k: pool[k] for k in ("kind", "label", "total", "granted", "unallocated")} | {"quote": ""}]}
        for pool in truth["pools"]
    ]
    cla = {"document": "synthetic_cla.md", "status": "executed", "execution_date": truth["cla"]["execution_date"],
           "lenders": [{"name": lender["name"]} for lender in truth["cla"]["lenders"]],
           "valuation_cap": truth["cla"]["valuation_cap"]}
    findings = validate_captable(JUNE, register=register, pool_docs=pool_docs, clas=[cla],
                                 register_captable=MARCH, pool_captable=MARCH)
    by_check = {}
    for finding in findings:
        by_check.setdefault(finding["check"], []).append(finding)
    statuses = {check: [f["status"] for f in items] for check, items in by_check.items()}
    assert statuses["issued_total_common"] == ["pass"]
    assert statuses["issued_total_preferred_a"] == ["pass"]
    assert statuses["diluted_equation"] == ["pass"]
    assert statuses["diluted_rowsum"] == ["pass"]
    assert statuses["register_reconciliation"] == ["pass"]
    assert "register_only_holder" not in statuses and "register_mismatch" not in statuses
    assert statuses["pool_consistency"] == ["pass"]
    assert "3 pool figures agree" in by_check["pool_consistency"][0]["detail"]
    assert [f["severity"] for f in by_check["cla_lender_is_shareholder"]] == ["info"]
    assert statuses["cla_lender_is_shareholder"] == ["pass"]
    assert "Bruno Muster" in by_check["cla_lender_is_shareholder"][0]["detail"]
    assert "cla_possibly_converted" not in statuses and "nominal_floor" not in statuses

    cross = check_cross_snapshot(MARCH, JUNE)
    assert [f["check"] for f in cross] == ["shrinking_holder"]
    assert "Bruno Muster" in cross[0]["detail"]


def test_register_mistakes_surface_in_reconciliation_not_only_in_evidence():
    """The stacked-history trap (200000) passes evidence but fails reconciliation."""
    entries = register_entries()
    entries[1]["current_common"] = 200000
    register = {"as_of_date": {"value": "2026-03-31"}, "entries": entries}
    findings = validate_captable(MARCH, register=register)
    mismatches = [f for f in findings if f["check"] == "register_mismatch"]
    assert len(mismatches) == 1 and "Bruno Muster" in mismatches[0]["detail"]


# --- CLA term sheet (cla_review fixture): planted absences, unsigned --------

TERM_SHEET_QUOTES = {
    "borrower_name": ("Fixture Robotics AG", "Fixture Robotics AG, Zurich (CHE-999.999.999)."),
    "signatures_complete": (False, "For the Borrower: Fixture Robotics AG *(unsigned)*"),
    "principal_total": (150000, "CHF 150,000 from Fixture Angels, Zug"),
    "principal_currency": ("CHF", "CHF 150,000 from Fixture Angels, Zug"),
    "interest_mode": ("fixed", "4% per annum, accruing"),
    "interest_rate_pct": (4, "4% per annum, accruing"),
    "interest_day_count": ("act/365", "calculated on the actual number of days elapsed over a 365-day year"),
    "interest_compounding": ("simple", "not compounded"),
    "maturity_date": ("2028-08-15", "i.e. on 15 August 2028"),
    "qefr_present": (True, "Qualified Equity Financing Round"),
    "qefr_min_raise": (3000000, "gross proceeds of at least CHF 3,000,000"),
    "qefr_mandatory": (True, "Upon the closing of the Qualified Equity Financing Round, the outstanding loan balance including accrued interest converts"),
    "valuation_cap": (12000000, "pre-money valuation of CHF 12,000,000"),
    "discount_pct": (20, "less a discount of 20%"),
    "subordinated": (True, "subordinated within the meaning of art. 725b para. 4 no. 1 CO"),
    "subordination_scope": ("loan_balance_full", "The Loans, including accrued interest, are subordinated"),
    "conversion_capital_sources": (["conditional_capital", "consents"], "issued out of the conditional share capital of the Borrower or, failing that, by way of an ordinary capital increase to which the existing shareholders have consented in advance"),
    "shareholder_consents_referenced": (True, "to which the existing shareholders have consented in advance"),
    "sha_accession_required": (True, "Upon conversion the Investors accede to the shareholders' agreement"),
    "governing_law": ("Swiss law", "Swiss law; courts of Zurich."),
    "denominator_basis": ("unstated", None),
    # term-sheet provisions (cla_terms.md group added for cla_review)
    "aggregate_amount_min": (300000, "minimum aggregate amount of CHF 300,000 for the first closing"),
    "aggregate_amount_max": (500000, "Up to an aggregate amount of CHF 500,000"),
    "lead_investor": ("Fixture Angels", "CHF 150,000 from Fixture Angels, Zug"),
    "accession_of_further_investors": (True, "Additional investors may, with the consent of the Borrower and the Lead Investor, accede to this Term Sheet"),
    "pre_emption_reduction": (True, "The Investment Amount may be reduced to the extent existing shareholders of the Borrower exercise their pre-emption rights."),
    "conversion_share_class": ("the same class of shares issued in that round (expected: preferred A shares)", "converts into the same class of shares issued in that round (expected: preferred A shares)"),
    "non_qualified_voluntary_conversion": (True, "If an equity financing round closes that does not qualify, each Investor may elect to convert its Loan"),
    "binding_provisions": ("Confidentiality, Legal Fees and Expenses, Exclusivity, Applicable Law and Jurisdiction", "Only the sections marked \"Binding\" (Confidentiality, Legal Fees and Expenses, Exclusivity, Applicable Law and Jurisdiction) are legally binding."),
    "exclusivity_present": (True, "the Borrower shall not solicit or negotiate any other convertible loan financing"),
    "exclusivity_until": ("2026-09-30", "Until 30 September 2026"),
    "investor_majority": ("Investors holding at least two thirds of the aggregate principal amount of the Loans", "require the consent of Investors holding at least two thirds of the aggregate principal amount of the Loans"),
    "legal_fees_each_party_own": (True, "Each party bears its own costs and expenses"),
    "documentation_form": ("seca_short_form", "based on the SECA CLA Model Documentation (short form)"),
    "documentation_counsel": ("Fixture Legal AG", "drafted by Fixture Legal AG, Zurich, as counsel to the Borrower"),
}


def _term_sheet_extraction() -> dict:
    """The faithful extraction: every planted value quoted, every absence declared."""
    truth = GROUND_TRUTH["cla_term_sheet"]
    output: dict = {"status": truth["status"], "status_evidence": "Not signed.", "comments": None}
    absent = []
    planted = {**truth, **truth["term_sheet_only_fields"]}
    for field in _BUILT["quoted_fields"]:
        value, quote = TERM_SHEET_QUOTES.get(field, (None, None))
        if field in planted and field not in TERM_SHEET_QUOTES:
            value = planted[field]  # planted absences: None / False / "unstated"
        output[field] = {"value": value, "quote": quote}
        if quote is None:
            absent.append(field)
    output["lenders"] = [
        {"name": lender["name"], "kind": lender["kind"], "domicile": lender["domicile"],
         "principal_amount": lender["principal_amount"],
         "quote": "CHF 150,000 from Fixture Angels, Zug"}
        for lender in truth["lenders"]
    ]
    output["missing_terms"] = [{"term": field, "sections_scanned": ["whole term sheet"]} for field in absent]
    return output


def test_term_sheet_faithful_extraction_passes_and_planted_absences_are_declared():
    truth = GROUND_TRUTH["cla_term_sheet"]
    output = _term_sheet_extraction()
    planted = {**truth, **truth["term_sheet_only_fields"]}
    for field, (value, _quote) in TERM_SHEET_QUOTES.items():
        assert planted[field] == value, field
    assert not cla_reviewer(text("synthetic_cla_term_sheet.md"))(output).problems
    declared = {entry["term"] for entry in output["missing_terms"]}
    assert set(truth["expected_missing_terms"]) <= declared


def test_term_sheet_invented_change_of_control_is_rejected():
    output = _term_sheet_extraction()
    output["coc_present"] = {"value": True, "quote": "upon a change of control the Loans convert or are repaid at 2.0x"}
    output["missing_terms"] = [e for e in output["missing_terms"] if e["term"] != "coc_present"]
    found = cla_reviewer(text("synthetic_cla_term_sheet.md"))(output).problems
    assert found and "coc_present: quote not found verbatim" in found[0]


def test_term_sheet_absence_without_missing_terms_entry_is_rejected():
    output = _term_sheet_extraction()
    output["missing_terms"] = [e for e in output["missing_terms"] if e["term"] != "maturity_conversion_present"]
    found = cla_reviewer(text("synthetic_cla_term_sheet.md"))(output).problems
    assert found and "maturity_conversion_present" in found[-1]
