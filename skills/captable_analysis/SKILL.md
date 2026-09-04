# captable_analysis

Analyzes a cap-table snapshot stored by `captable_build` (issue #17,
skill 2). All numbers are computed deterministically in
`lib/captable/model.py` and `lib/captable/rubric.py`; the LLM's only job is
to phrase a narrative over the computed JSON — it may not compute or invent
any figure.

## Usage

```bash
python -m skills.captable_analysis run --dataset <startup> \
    [--as-of 2026-03-31] [--pre-money 8000000] [--investment 2000000]
```

Reads `insights/captable/latest.json` (or the named snapshot), then:

- accrues each executed CLA's loan balance to the valuation date under its
  extracted day-count and compounding (unstated → act/365 simple, recorded
  as an assumption),
- computes conversion scenarios for a hypothetical round under all three
  market methods (pre_money / percentage_ownership / dollars_invested),
  side by side — CLAs are usually silent on the method, so no method is
  ever silently chosen; round parameters default from the data (largest
  cap, QEFR minimum) and are always recorded as assumptions,
- estimates the 1% issuance stamp duty against the CHF 1M lifetime
  exemption,
- applies the red-flag rubric (founder majority, investor dominance, dead
  equity, fully-diluted-definition ambiguity),
- writes `insights/captable/analysis_scenarios.json` and a narrative
  `analysis.md`.

Requires a snapshot: run `python -m skills.captable_build build` first.
