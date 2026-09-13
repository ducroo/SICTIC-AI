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


# --- the planted quirks must stay in the documents ---------------------------

@pytest.mark.parametrize("name, needle", [
    ("synthetic_register.md", "&#124;"),
    ("synthetic_register.md", "| 3 | 200'000 300'000 | | 15.38% 23.08% |"),
    ("synthetic_register.md", "| | | 2 | 150 ' 000 |"),
    ("synthetic_register.md", "| n/a | 500 ' 000 |"),
    ("synthetic_register.md", "| 100 000 | - |"),
    ("synthetic_register.md", "| # |"),
    ("synthetic_pool_overview.md", "| | | | |\n| --- |"),
    ("synthetic_pool_overview.md", "| Pool size (options) | 25000 | # |"),
    ("synthetic_pool_overview.md", "% of shares issued (1,300,000)"),
    ("synthetic_esop_plan.md", "Date:\n\n15 February 2026"),
    ("synthetic_cla.md", "Lender 2 contributes CHF 50,000.00"),
])
def test_planted_quirks_are_still_in_the_documents(name, needle):
    assert needle in text(name)


def test_page_marker_sits_between_two_table_rows():
    lines = text("synthetic_register.md").splitlines()
    marker = lines.index("<!-- sictic-page:2 -->")
    before = next(item for item in reversed(lines[:marker]) if item.strip())
    after = next(item for item in lines[marker + 1:] if item.strip())
    assert before.startswith("| 2 | Bruno") and after.startswith("| 3 | Alpina")


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
