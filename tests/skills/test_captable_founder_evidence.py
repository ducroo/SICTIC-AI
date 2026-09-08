"""Missing founder evidence must not become a zero percentage or a pass."""
from datetime import date

import pytest

from lib.captable.rubric import apply_rubric
from lib.captable.render_markdown import render_report
from skills.captable.captable import build_scenarios
from tests.skills.test_captable_render import _snapshot


@pytest.mark.parametrize("holders", [
    [],
    [{"role": "founder", "diluted_count": 0}],
    [{"role": "founder", "holdings": []}],
    [{"role": "investor", "diluted_count": 100}],
    [{"role": "unknown", "diluted_count": 100}],
    [{"role": "founder", "holdings": [{"count": None}]},
     {"role": "investor", "diluted_count": 100}],
    [{"role": "founder", "diluted_count": 20},
     {"role": "founder", "holdings": []},
     {"role": "investor", "diluted_count": 80}],
])
def test_missing_evidence_cannot_pass_or_assume_zero(holders):
    findings = {f["item"]: f for f in apply_rubric({"stakeholders": holders})}
    assert findings["founder_majority"]["status"] == "insufficient_evidence"
    assert "cannot be assessed" in findings["founder_majority"]["detail"]
    assert "investor_dominance" not in findings


@pytest.mark.parametrize("founder_shares,status", [(0, "flag"), (49, "flag"), (50, "ok"), (70, "ok")])
@pytest.mark.parametrize("field", ["diluted_count", "holdings"])
def test_evidenced_counts_preserve_threshold_and_explicit_zero(founder_shares, status, field):
    founder = {"role": "founder"}
    founder[field] = founder_shares if field == "diluted_count" else [{"count": founder_shares}]
    data = {"stakeholders": [founder, {"role": "investor", "diluted_count": 100 - founder_shares}]}
    findings = {f["item"]: f for f in apply_rubric(data)}
    assert findings["founder_majority"]["status"] == status
    assert f"{founder_shares:.1f}%" in findings["founder_majority"]["detail"]
    if founder_shares == 0:
        assert findings["investor_dominance"]["status"] == "flag"


def test_report_and_scenarios_disclose_missing_founder_roles():
    data = _snapshot()
    for holder in data["stakeholders"]:
        if holder.get("role") == "founder":
            holder["role"] = "unknown"
    computed = build_scenarios(data, valuation_date=date(2026, 9, 8))
    assert computed["scenarios"]
    assert all(s["founders_post_round_pct"] is None for s in computed["scenarios"])
    assert not any(f["item"] == "founder_majority_post_round" for f in computed["scenario_flags"])
    computed["rubric"] = apply_rubric(data)
    computed["rubric_scope_note"] = "Source-date findings."
    output = render_report(data, computed, "Review founder roles.")
    assert "insufficient_evidence" in output
    assert "Founder ownership is unknown" in output
    assert "Founders hold 0.0%" not in output


def test_missing_founder_counts_are_unknown_in_current_ownership_table():
    data = _snapshot()
    founder = data["stakeholders"][0]
    founder["diluted_count"] = None
    founder["holdings"] = []
    computed = build_scenarios(data, valuation_date=date(2026, 9, 8))
    assert computed["ownership_by_role_today"]["founder"] is None
