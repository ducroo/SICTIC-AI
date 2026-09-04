"""Analyze a stored cap-table snapshot (issue #17, skill 2).

Reads the snapshot captable_build stored (``latest.json`` by default, or a
specific ``as_of``), computes conversion scenarios and the red-flag rubric
deterministically, and lets the LLM do exactly one thing: phrase a
narrative over the computed JSON.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from lib.captable.model import Note, convert_in_round, loan_balance, stamp_duty
from lib.captable.rubric import apply_rubric, ownership_by_role
from lib.datasets.paths import dataset_insights_path
from lib.infrastructure.ai_text_generation import generate_markdown
from lib.infrastructure.configuration import load_repository_config
from lib.infrastructure.logging import get_logger
from lib.insights import InsightFile
from lib.model_config import llm_model
from lib.storage import get_storage

logger = get_logger(__name__)


def _value(entry: Any) -> Any:
    if isinstance(entry, dict) and "value" in entry:
        return entry["value"]
    return entry


def _load_snapshot(dataset_name: str, as_of: str | None) -> dict[str, Any]:
    storage = get_storage()
    insights_rel = dataset_insights_path(dataset_name)
    rel = (
        f"{insights_rel}/captable/snapshots/{as_of}.json"
        if as_of
        else f"{insights_rel}/captable/latest.json"
    )
    if not storage.exists(rel):
        raise ValueError(
            f"No cap-table snapshot at {rel!r}; run captable_build first."
        )
    return json.loads(storage.read_text(rel))


def _parse_date(value: Any) -> date | None:
    from lib.captable.snapshot import normalize_iso_date

    value = normalize_iso_date(value) if isinstance(value, str) else value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
    return None


def _existing_shares(snapshot: dict[str, Any]) -> dict[str, float]:
    """Pre-round fully-diluted shares per holder (treasury excluded).

    Pool/reserved positions still dilute, but they are not shareholders —
    label them so scenario ownership tables don't list them beside people.
    """
    shares: dict[str, float] = {}
    for stakeholder in snapshot.get("stakeholders", []):
        if stakeholder.get("kind") == "treasury":
            continue
        diluted = stakeholder.get("diluted_count")
        if diluted is None:
            diluted = sum(
                h.get("count") or 0.0
                for h in stakeholder.get("holdings", [])
            )
        if diluted:
            name = stakeholder.get("name", "unknown")
            if stakeholder.get("kind") in ("pool", "authorized_capital"):
                name = f"[reserved pool] {name}"
            shares[name] = diluted
    return shares


def _notes_from_snapshot(
    snapshot: dict[str, Any], valuation_date: date
) -> tuple[list[Note], list[str]]:
    notes: list[Note] = []
    assumptions: list[str] = []
    for cla in snapshot.get("convertibles", []):
        if cla.get("status") != "executed":
            continue
        principal = _value(cla.get("principal_total"))
        if not principal:
            continue
        rate = _value(cla.get("interest_rate_pct")) or 0.0
        day_count = _value(cla.get("interest_day_count"))
        if day_count in (None, "unstated"):
            day_count = "act/365"
            assumptions.append(
                f"{cla.get('document')}: day count unstated; act/365 assumed."
            )
        compounding = _value(cla.get("interest_compounding"))
        if compounding in (None, "unstated"):
            compounding = "simple"
            assumptions.append(
                f"{cla.get('document')}: compounding unstated; simple assumed."
            )
        elif compounding == "compound_other":
            assumptions.append(
                f"{cla.get('document')}: non-annual compounding stated; "
                "computed as ANNUAL compounding (approximation, slightly "
                "understates the balance)."
            )
        start = _parse_date(_value(cla.get("execution_date")))
        if start is None:
            start = valuation_date
            assumptions.append(
                f"{cla.get('document')}: execution date unparseable; "
                "no interest accrued in the scenarios."
            )
        elif start > valuation_date:
            start = valuation_date
            assumptions.append(
                f"{cla.get('document')}: execution date "
                f"{_value(cla.get('execution_date'))!r} lies after the "
                "valuation date (typo/OCR?); no interest accrued."
            )
        balance = loan_balance(
            float(principal),
            float(rate),
            start,
            valuation_date,
            day_count=day_count,
            compounding="compound_annual"
            if str(compounding).startswith("compound")
            else "simple",
        )
        notes.append(
            Note(
                label=f"lenders of {cla.get('document')}",
                balance=balance,
                cap=_value(cla.get("valuation_cap")),
                discount_pct=_value(cla.get("discount_pct")),
                floor=_value(cla.get("valuation_floor")),
            )
        )
    return notes, assumptions


def build_scenarios(
    snapshot: dict[str, Any],
    *,
    pre_money: float | None = None,
    investment: float | None = None,
    valuation_date: date | None = None,
) -> dict[str, Any]:
    """Deterministic scenario computation; all defaults become assumptions."""
    valuation_date = valuation_date or date.today()
    assumptions: list[str] = [
        f"Loan balances are accrued to the analysis date "
        f"{valuation_date}; the snapshot itself describes the company as "
        f"of {snapshot.get('as_of_date', 'unknown')}."
    ]
    notes, note_assumptions = _notes_from_snapshot(snapshot, valuation_date)
    assumptions += note_assumptions

    caps = [note.cap for note in notes if note.cap]
    qefr_mins = [
        _value(cla.get("qefr_min_raise"))
        for cla in snapshot.get("convertibles", [])
        if cla.get("status") == "executed"
        and _value(cla.get("qefr_min_raise"))
    ]
    if pre_money is None:
        if caps:
            pre_money = float(max(caps))
            assumptions.append(
                f"Hypothetical round pre-money set to the largest CLA "
                f"valuation cap ({pre_money:,.0f}) — an assumption, not a "
                "prediction."
            )
        else:
            invested = sum(
                s.get("invested_amount") or 0.0
                for s in snapshot.get("stakeholders", [])
            )
            pre_money = max(2 * invested, 1_000_000.0)
            assumptions.append(
                f"No valuation cap available; hypothetical pre-money set "
                f"to 2x cumulative invested capital ({pre_money:,.0f})."
            )
    if investment is None:
        investment = float(min(qefr_mins)) if qefr_mins else 0.2 * pre_money
        assumptions.append(
            "Hypothetical round size set to the QEFR minimum raise."
            if qefr_mins
            else "Hypothetical round size set to 20% of pre-money."
        )

    existing = _existing_shares(snapshot)
    nominal_values = [
        c.get("nominal_value")
        for c in snapshot.get("share_classes", [])
        if c.get("nominal_value")
    ]
    scenarios = (
        convert_in_round(
            pre_money_valuation=pre_money,
            new_investment=investment,
            existing_shares=existing,
            notes=notes,
            nominal_value=min(nominal_values) if nominal_values else None,
        )
        if existing
        else []
    )

    cumulative_paid_in = sum(
        s.get("invested_amount") or 0.0
        for s in snapshot.get("stakeholders", [])
    )
    note_balance_total = sum(note.balance for note in notes)
    duty = stamp_duty(cumulative_paid_in, investment + note_balance_total)
    if duty:
        from lib.captable.model import STAMP_DUTY_EXEMPTION_CHF

        remaining = max(0.0, STAMP_DUTY_EXEMPTION_CHF - cumulative_paid_in)
        exemption_note = (
            f"the CHF {STAMP_DUTY_EXEMPTION_CHF:,.0f} lifetime exemption "
            + (
                f"is already exhausted by {cumulative_paid_in:,.0f} of "
                "historical paid-in capital"
                if remaining == 0
                else f"has {remaining:,.0f} remaining"
            )
        )
        assumptions.append(
            "Stamp-duty estimate treats cumulative invested amounts in the "
            f"cap table as the paid-in capital history; {exemption_note}."
        )

    founder_names = {
        stakeholder.get("name", "unknown")
        for stakeholder in snapshot.get("stakeholders", [])
        if stakeholder.get("role") == "founder"
    }

    def scenario_dict(s):
        founders_post = sum(
            pct
            for holder, pct in s.ownership_pct.items()
            if holder in founder_names
        )
        return {
            "method": s.method,
            "price_per_share": round(s.price_per_share, 4),
            "ownership_pct": {
                k: round(v, 2) for k, v in sorted(s.ownership_pct.items())
            },
            "founders_post_round_pct": round(founders_post, 2),
            "note_conversion_prices": {
                k: round(v, 4) for k, v in s.note_prices.items()
            },
            "warnings": s.warnings,
        }

    return {
        "valuation_date": str(valuation_date),
        "snapshot_as_of": snapshot.get("as_of_date"),
        "hypothetical_round": {
            "pre_money": pre_money,
            "investment": investment,
        },
        "note_balances": {
            note.label: round(note.balance, 2) for note in notes
        },
        "scenarios": [scenario_dict(s) for s in scenarios],
        "scenario_flags": [
            {
                "item": "founder_majority_post_round",
                "status": "flag",
                "severity": "high",
                "detail": (
                    f"Founders fall below 50% fully diluted in every "
                    f"modelled scenario ("
                    + ", ".join(
                        f"{sd['method']}: {sd['founders_post_round_pct']}%"
                        for sd in (scenario_dict(s) for s in scenarios)
                    )
                    + ") — the current-state founder_majority rubric item "
                    "does not survive the hypothetical round."
                ),
            }
        ]
        if scenarios
        and all(
            scenario_dict(s)["founders_post_round_pct"] < 50
            for s in scenarios
        )
        else [],
        "stamp_duty": {
            "estimate_chf": round(duty, 2),
            "exemption_chf": 1_000_000,
            "exemption_remaining_chf": round(
                max(0.0, 1_000_000 - cumulative_paid_in), 2
            ),
            "note": "1% on contributions above the CHF 1M lifetime "
            "exemption; historical paid-in capital counts against it.",
        },
        "stamp_duty_estimate_chf": round(duty, 2),
        "ownership_by_role_today": {
            k: round(v, 2)
            for k, v in sorted(ownership_by_role(snapshot).items())
        },
        "assumptions": assumptions,
    }


async def captable_analysis(
    dataset_name: str,
    *,
    as_of: str | None = None,
    pre_money: float | None = None,
    investment: float | None = None,
) -> dict[str, Any]:
    """Full analysis: deterministic computation + LLM narrative."""
    snapshot = _load_snapshot(dataset_name, as_of)
    computed = build_scenarios(
        snapshot, pre_money=pre_money, investment=investment
    )
    computed["rubric_scope_note"] = (
        "Rubric findings describe the company AS OF the snapshot date, "
        "not the hypothetical post-round state; see "
        "scenarios[].founders_post_round_pct for post-round ownership."
    )
    computed["rubric"] = apply_rubric(snapshot)
    computed["validation"] = snapshot.get("validation", [])
    computed["diligence_questions"] = snapshot.get(
        "diligence_questions", []
    )
    computed["aggregation"] = {
        key: snapshot.get("aggregation", {}).get(key)
        for key in (
            "outstanding_principal_total",
            "ten_twenty_rule",
            "executed_count",
            "term_sheet_count",
        )
    }

    prompt_template = load_repository_config("captable_analysis")[
        "narrative_prompt"
    ]
    narrative = await generate_markdown(
        f"{prompt_template.strip()}\n\n### COMPUTED JSON\n\n"
        f"```json\n{json.dumps(computed, ensure_ascii=False, indent=2)}\n```"
    )

    storage = get_storage()
    insights_rel = dataset_insights_path(dataset_name)
    storage.mkdir(f"{insights_rel}/captable")
    storage.write_text(
        f"{insights_rel}/captable/analysis_scenarios.json",
        json.dumps(computed, ensure_ascii=False, indent=2),
    )
    # The narrative is model-dependent, so it goes through the repo's
    # InsightFile convention (model-slug filename, manifest, freshness).
    # The snapshot store itself stays as designed (§2.3): versioned by
    # as-of date, not by model — a deliberate deviation.
    insight = InsightFile(dataset_name, "captable_analysis", llm_model())
    insight.save(narrative)
    logger.info(
        "[%s] Stored captable analysis insight at %s",
        dataset_name,
        insight.path,
    )
    return {
        "computed": computed,
        "narrative": narrative,
        "insight_path": insight.path,
    }
