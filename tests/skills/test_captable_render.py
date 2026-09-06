"""Tests for the deterministic HTML renderer (no LLM, no clock)."""

from __future__ import annotations

import json

import pytest

from lib.captable.render_html import render_html
from lib.captable.rubric import ownership_by_role


def _snapshot() -> dict:
    return {
        "dataset": "fixture-robotics",
        "as_of_date": "2026-06-30",
        "generated_at": "2026-09-05T12:00:00+00:00",
        "tool_version": "captable_build/0.3",
        "sources": [
            {"doc": "captable.md", "class": "captable_current",
             "date": "2026-06-30"},
            {"doc": "cla.md", "class": "cla_executed", "date": None},
        ],
        "share_classes": [
            {"id": "common", "name": "Common", "nominal_value": 0.10,
             "votes_per_share": 1},
        ],
        "stakeholders": [
            {"name": "Petra Muster", "kind": "individual", "role": "founder",
             "holdings": [{"class_id": "common", "count": 600_000}],
             "diluted_count": 600_000},
            {"name": "Angel <script>alert(1)</script>", "kind": "entity",
             "role": "investor", "group": "Syndicate A",
             "holdings": [{"class_id": "common", "count": 300_000}],
             "diluted_count": 300_000},
            {"name": "Treasury", "kind": "treasury", "role": "company",
             "holdings": [{"class_id": "common", "count": 50_000}],
             "diluted_count": None},
            {"name": "ESOP", "kind": "pool", "role": "employee",
             "holdings": [], "diluted_count": 100_000},
        ],
        "pools": [
            {"kind": "esop", "label": "ESOP 2025", "total": 100_000,
             "granted": 40_000, "unallocated": 60_000},
        ],
        "totals": {
            "by_class": [{"class_id": "common", "issued_total": 950_000}],
            "diluted_total": 1_000_000,
        },
        "fully_diluted_definition": {"value": "full_pools"},
        "convertibles": [
            {"document": "cla.md", "status": "executed",
             "principal_total": {"value": 250_000},
             "currency": {"value": "CHF"},
             "interest_rate_pct": {"value": 5},
             "maturity_date": {"value": "2025-12-31"},
             "discount_pct": {"value": 20},
             "valuation_cap": {"value": 8_000_000},
             "lenders": [{"name": {"value": "Petra Muster"}}]},
        ],
        "aggregation": {
            "outstanding_principal_total": 250_000.0,
            "outstanding_unknown_amounts": 0,
            "ten_twenty_rule": {
                "max_lenders_on_identical_terms": 1,
                "total_lenders_all_terms": 1,
                "ten_rule": "within", "twenty_rule": "within",
            },
            "maturity": [
                {"document": "cla.md", "maturity_date": "2025-12-31",
                 "status": "expired_check_for_conversion",
                 "detail": "Maturity passed."},
            ],
            "esignature": [
                {"document": "cla.md", "signatures_complete_claimed": True,
                 "esign_markers": None, "corroborated": "not_applicable"},
            ],
        },
        "assessment": [{"document": "cla.md", "worst_severity": "medium"}],
        "validation": [
            {"check": "issued_totals", "status": "pass",
             "severity": "info", "detail": "All classes add up."},
            {"check": "shrinking_holder", "status": "warn",
             "severity": "medium", "detail": "Bruno 300k -> 250k."},
        ],
        "diligence_questions": ["Ask about the bridge."],
        "assumptions": ["as_of derived from the document header."],
    }


def test_percentages_match_ownership_by_role() -> None:
    """The bar chart may never disagree with the rubric's numbers."""
    html = render_html(_snapshot())
    pct = ownership_by_role(_snapshot())
    for role, share in pct.items():
        assert f"{role} {share:.1f}%" in html


def test_holder_percentage_uses_rubric_denominator() -> None:
    html = render_html(_snapshot())
    # 600k of 1,000,000 non-treasury diluted (600k+300k+100k pool)
    assert "60.00%" in html
    # Treasury is excluded from the denominator, not silently dropped.
    assert "excluded" in html


def test_llm_extracted_strings_are_escaped() -> None:
    html = render_html(_snapshot())
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_maturity_status_comes_from_aggregation_not_a_clock() -> None:
    html = render_html(_snapshot())
    assert "expired_check_for_conversion" in html


def test_esign_not_applicable_rendered_neutrally() -> None:
    html = render_html(_snapshot())
    assert "not_applicable" in html


def test_empty_snapshot_renders() -> None:
    html = render_html({"dataset": "empty"})
    assert html.startswith("<!doctype html>")
    assert "No holder data extracted." in html


def test_deterministic_output() -> None:
    assert render_html(_snapshot()) == render_html(_snapshot())


def test_scenarios_only_attached_for_matching_snapshot(mock_env) -> None:
    from lib.datasets.paths import (
        dataset_insights_path,
        dataset_location_for_domain,
    )
    from lib.storage import get_storage
    from skills.captable_analysis.captable_analysis import render_captable

    storage = get_storage()
    location = dataset_location_for_domain("renderco", "startups")
    storage.mkdir(location.raw_rel)
    storage.mkdir(location.insights_rel)
    insights_rel = dataset_insights_path("renderco")
    storage.mkdir(f"{insights_rel}/captable/snapshots")
    storage.write_text(
        f"{insights_rel}/captable/latest.json",
        json.dumps(_snapshot()),
    )
    stale = {
        "snapshot_as_of": "2026-03-31",  # older state than the snapshot
        "scenarios": [{"method": "pre_money", "price_per_share": 8.0,
                       "founders_post_round_pct": 55.0, "warnings": []}],
    }
    storage.write_text(
        f"{insights_rel}/captable/analysis_scenarios.json",
        json.dumps(stale),
    )
    result = render_captable("renderco")
    assert result["scenarios_included"] is False
    assert result["scenarios_status"] == "stale"
    assert "different snapshot state" in result["html"]
    assert storage.exists(f"{insights_rel}/captable/captable.html")

    from lib.captable.snapshot import snapshot_fingerprint

    fresh = dict(
        stale,
        snapshot_as_of="2026-06-30",
        snapshot_fingerprint=snapshot_fingerprint(_snapshot()),
    )
    storage.write_text(
        f"{insights_rel}/captable/analysis_scenarios.json",
        json.dumps(fresh),
    )
    result = render_captable("renderco")
    assert result["scenarios_included"] is True
    assert result["scenarios_status"] == "included"
    assert "pre_money" in result["html"]


def test_corrected_rebuild_with_same_date_drops_old_scenarios(mock_env) -> None:
    """Review point 3 (PR #61): matching on the as-of date alone let a
    corrected rebuild render outdated dilution beside updated ownership."""
    from lib.captable.snapshot import snapshot_fingerprint
    from lib.datasets.paths import (
        dataset_insights_path,
        dataset_location_for_domain,
    )
    from lib.storage import get_storage
    from skills.captable_analysis.captable_analysis import render_captable

    storage = get_storage()
    location = dataset_location_for_domain("renderco3", "startups")
    storage.mkdir(location.raw_rel)
    storage.mkdir(location.insights_rel)
    insights_rel = dataset_insights_path("renderco3")
    storage.mkdir(f"{insights_rel}/captable/snapshots")
    original = _snapshot()
    scenarios = {
        "snapshot_as_of": original["as_of_date"],
        "snapshot_fingerprint": snapshot_fingerprint(original),
        "scenarios": [{"method": "pre_money", "price_per_share": 8.0,
                       "founders_post_round_pct": 55.0, "warnings": []}],
    }
    storage.write_text(
        f"{insights_rel}/captable/analysis_scenarios.json",
        json.dumps(scenarios),
    )

    # A rebuild with identical content but a new timestamp keeps them.
    rebuilt_same = dict(original, generated_at="2026-09-06T08:00:00+00:00")
    storage.write_text(
        f"{insights_rel}/captable/latest.json", json.dumps(rebuilt_same)
    )
    assert render_captable("renderco3")["scenarios_status"] == "included"

    # A corrected rebuild with the SAME as-of date drops them.
    corrected = json.loads(json.dumps(original))
    corrected["stakeholders"][0]["holdings"][0]["count"] = 550_000
    corrected["stakeholders"][0]["diluted_count"] = 550_000
    storage.write_text(
        f"{insights_rel}/captable/latest.json", json.dumps(corrected)
    )
    result = render_captable("renderco3")
    assert result["scenarios_status"] == "stale"
    assert result["scenarios_included"] is False
    assert "different snapshot state" in result["html"]
    assert "pre_money" not in result["html"]

    # Legacy scenarios without a fingerprint are treated as stale too.
    storage.write_text(
        f"{insights_rel}/captable/latest.json", json.dumps(original)
    )
    storage.write_text(
        f"{insights_rel}/captable/analysis_scenarios.json",
        json.dumps({k: v for k, v in scenarios.items()
                    if k != "snapshot_fingerprint"}),
    )
    assert render_captable("renderco3")["scenarios_status"] == "stale"


def test_named_as_of_renders_into_snapshots_dir(mock_env) -> None:
    from lib.datasets.paths import (
        dataset_insights_path,
        dataset_location_for_domain,
    )
    from lib.storage import get_storage
    from skills.captable_analysis.captable_analysis import render_captable

    storage = get_storage()
    location = dataset_location_for_domain("renderco2", "startups")
    storage.mkdir(location.raw_rel)
    storage.mkdir(location.insights_rel)
    insights_rel = dataset_insights_path("renderco2")
    storage.mkdir(f"{insights_rel}/captable/snapshots")
    storage.write_text(
        f"{insights_rel}/captable/snapshots/2026-06-30.json",
        json.dumps(_snapshot()),
    )
    result = render_captable("renderco2", as_of="2026-06-30")
    assert result["path"].endswith("captable/snapshots/2026-06-30.html")
    assert storage.exists(result["path"])


def test_missing_snapshot_raises(mock_env) -> None:
    from lib.datasets.paths import dataset_location_for_domain
    from lib.storage import get_storage
    from skills.captable_analysis.captable_analysis import render_captable

    location = dataset_location_for_domain("renderco3", "startups")
    get_storage().mkdir(location.raw_rel)
    with pytest.raises(ValueError, match="run captable_build first"):
        render_captable("renderco3")
