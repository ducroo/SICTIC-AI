# Cap table and convertible loan analysis

`captable_build` extracts and validates source facts; `captable` computes
conversion scenarios and produces a Markdown report. The model extracts quoted
facts and writes commentary. Python performs calculations and renders numeric
tables. Quote verification supports review; it cannot prove semantic correctness.

## Artifacts and reuse

A complete generated run has five logical artifacts per model:

| Skill | Artifact | Format | Directory |
|---|---|---|---|
| `captable_build` | classification | JSON | `insights/captable-build/` |
| `captable_build` | loan-extraction | JSON | `insights/captable-build/` |
| `captable_build` | table-extraction | JSON | `insights/captable-build/` |
| `captable_build` | consolidated | JSON | `insights/captable-build/` |
| `captable` | final report | Markdown | `insights/` |

`InsightFile` supplies filenames, model suffixes, manual precedence and freshness
metadata. Generated reuse requires matching indexed startup revisions and effective
configuration. Extraction depends on classification content; consolidation depends
on all selected inputs and its evaluation date. The report depends on consolidated
content, scenario inputs, analysis date and narrative configuration. Manual outputs
win; editing a manual intermediate invalidates generated dependents. `--fresh`
bypasses generated build reuse while preserving manual overrides.

There are no dated output snapshots, latest pointers, HTML, scenario JSON or
separate assessment/aggregation caches. Source dates and extracted cap-table
versions remain data within JSON. Old stored files are untouched and are not
selected as inputs. Shared freshness metadata is additional infrastructure, not
another skill artifact.

## Build and report

Build classifies parsed documents, extracts convertible loans and cap-table,
register and pool evidence, then reconciles and consolidates them. Required
extraction failures raise without saving partial results. The term checklist and
assessment settings live in `config/captable_build/`. Assessment, aggregation and
signature scanning are recomputed when consolidation needs rebuilding.

Validation covers issued and diluted totals, holder row sums, register and pool
reconciliation, nominal floors and loan lifecycle questions. Register evidence is
paired with the cap-table version nearest its source date. Generated output history
is not used for comparisons.

The report reads reusable consolidated data, checking the same dependency keys
as the build, without building or synchronizing. Missing/stale generated inputs
raise with an instruction to run build first; manual consolidated data wins. Run build first when current source data is needed; bulk refresh
declares `captable-build` as the prerequisite of `captable`. Both canonical APIs
return a flat `list[InsightFile]` (the build returns its consolidated insight).

The report computes accrued balances, fixed maturity conversions, pre-money,
percentage-ownership and dollars-invested round scenarios, stamp duty and rubric
findings. Each loan retains its stated denominator basis and currency. Missing FX
rates block combined scenarios; hypothetical round defaults and unknown inputs
are disclosed. Interest accrues to the analysis date, separately from source dates.
Missing ownership counts or founder-role information produces an
`insufficient_evidence` finding, not a zero founder percentage. Explicitly
recorded zero founder holdings remain assessable.
Numeric tables are rendered in Python; `config/captable/narrative_prompt.md` controls
explanatory commentary.

## Usage

Start with a synchronized startup dataset, then run:

```bash
conda run -n sictic-env python -m skills.captable_build build --startup example
conda run -n sictic-env python -m skills.captable run --startup example
```

Harness commands are `/captable_build` and `/captable`. The report accepts
`--pre-money`, `--investment`, `--fx-rate CUR=RATE` and `--currency`.
`--dataset` remains a selector alias. The old `captable_analysis run` CLI and
`/captable_analysis` temporarily forward to `captable`; there is no `render`,
`snapshot` or `--as-of` command/option.

See the [build skill](../skills/captable_build/SKILL.md) for stage adapters and
[report skill](../skills/captable/SKILL.md) for input and reuse contracts.
The [design](captable-design.md) and [checks](captable-checks.md) explain the
financial model. Synthetic source fixtures and ground truth are under
`tests/fixtures/captable/`; pytest covers the model and artifact lifecycle without
live model calls.

## Known limitations / follow-ups

- The 33.33% discount reclassification threshold is **unverified with
  tax counsel** (it lives in `assessment_rules.json`, not code); the
  newly-issued-vs-treasury-shares tax question is likewise recorded as a
  verify-with-counsel item in [captable-design.md](captable-design.md).
- Anti-dilution provisions, phantom-share liabilities, and exit
  waterfalls are not yet extracted or modelled.
- Syndicate members are not resolved (the 10/20 outputs say so rather
  than reporting a false pass).
- Conversion notices are classified but not yet read to flip a CLA's
  status to `converted`; similarly, the register's transfer/acquisition
  entries are not yet mined as evidence for cross-version share movements
  (a documented transfer could resolve a `shrinking_holder` warning).
- Interest accrual starts at the execution date; the contractual value
  date of the actual disbursement (often a few business days later) is
  not extracted, so balances are marginally conservative-high.
- CLA disclosure schedules are not mined for non-captable diligence facts
  (license royalties, litigation, etc.) — that belongs to the dd_checks
  checklist flow, not this skill.
- Classification confidence varies slightly across runs (LLM-judged);
  classes have been stable in testing, and an eval suite over the fixture
  answer key is the planned guardrail.

## Report settings

`config/captable/settings.json` contains the adjustable report assumptions:

| Setting | Default | Meaning |
|---|---:|---|
| `founder_majority_min_pct` | 50 | Founder warning threshold, before and after the hypothetical round. |
| `investor_dominance_ratio` | 2 | Investor ownership relative to founder ownership. |
| `departed_ownership_max_pct` | 10 | Departed-holder warning threshold. |
| `fallback_pre_money_invested_multiplier` | 2 | Valuation multiplier when no CLA cap or explicit valuation is available. |
| `fallback_pre_money_minimum` | 1000000 | Minimum fallback valuation in the scenario currency. |
| `fallback_investment_pct` | 20 | Round size as a percentage of valuation when no QEFR minimum or explicit amount is available. |

These are required configuration values, without hardcoded fallback copies.
Explicit round inputs and extracted CLA caps/QEFR minima retain their precedence.
Settings changes invalidate generated reports through shared freshness checks;
build extraction artifacts and manual report precedence are unaffected.

## CLA comments

Each extracted CLA has a nullable `comments` string containing verbatim source
passages for unusual valuation/conversion terms. It is carried unchanged into
consolidated data and the final CLA table's Comments column. Multiple passages
retain line breaks; Markdown characters are escaped for display. Missing/null
comments, including older manual inputs without this field, display as empty.
These quotations are for human review, have no additional automated evidence
review, and do not change the calculations. The report explicitly notes that
quoted provisions may require manual adjustment. The changed extraction
configuration invalidates generated loan extractions through shared freshness.
