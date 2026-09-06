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

- accrues each executed CLA's loan balance to the analysis date under its
  extracted day-count and compounding (unstated → act/365 simple, recorded
  as an assumption; the accrual date vs the snapshot's as-of date is always
  disclosed); safe-harbor-capped loans accrue at the documented safe-harbor
  rate rather than the stated ceiling — an unquantified cap falls back to
  the ceiling with a loud overstatement disclosure,
- reports a `maturity_conversion_at_fixed_price` block whenever a CLA
  fixes a per-share price for post-maturity conversion (implied shares at
  the accrued balance, and the company value that price implies over the
  current fully-diluted count — the discount/cap scenario prices apply to
  round conversions only),
- computes conversion scenarios for a hypothetical round under all three
  market methods (`pre_money` / `percentage_ownership` /
  `dollars_invested`), side by side — CLAs are usually silent on the
  method, so no method is ever silently chosen; round parameters default
  from the data (largest cap, QEFR minimum) and are always recorded as
  assumptions,
- reports `founders_post_round_pct` per scenario and raises a structured
  `scenario_flags` entry (`founder_majority_post_round`) when founders fall
  below 50% in every modelled scenario,
- estimates the 1% issuance stamp duty as a structured `stamp_duty` block
  (estimate, CHF 1M lifetime exemption, remaining exemption),
- applies the red-flag rubric (founder majority, investor dominance, dead
  equity, fully-diluted-definition ambiguity) — explicitly scoped to the
  snapshot date via `rubric_scope_note`, never to the post-round state,
- labels reserved positions as `[reserved pool] …` in scenario ownership so
  pools are never listed as shareholders.

## Rendering (`render`)

```bash
python -m skills.captable_analysis render --dataset <startup> [--as-of DATE]
```

Renders the snapshot as a self-contained HTML one-pager — **no LLM
call**: every number is copied verbatim from the validated snapshot
(ownership bar by role, holder table with classification badges, share
classes, pools, CLA overhang with maturity/e-sign status, validation
traffic lights), so the visual a reviewer looks at can never drift from
the stored data. Percentages use the same denominator as
`rubric.ownership_by_role`. When `analysis_scenarios.json` exists AND was
computed over the same snapshot state — same as-of date AND same content
fingerprint (`snapshot_fingerprint`, a hash of the snapshot minus its
generation timestamp) — the conversion-scenario table is included.
Scenarios from another as-of, or from an earlier build of the same as-of
whose content has since changed, are skipped and the page says so
(re-run the analysis to refresh them). Written to
`insights/captable/captable.html` (or `snapshots/<as_of>.html`);
`captable_build` also writes it automatically on every build.

## Outputs

- `insights/captable/analysis_scenarios.json` — the computed JSON
  (prices rounded to 4 decimals, percentages to 2).
- The narrative, stored through the repository's `InsightFile` convention
  (`captable-analysis-<dataset>-<model-slug>.md`, manifest-tracked) since
  it is model-dependent.

Requires a snapshot: run `python -m skills.captable_build build` first.
