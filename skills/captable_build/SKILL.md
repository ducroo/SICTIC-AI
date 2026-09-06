# captable_build

Builds structured cap-table and convertible-loan facts for one startup
dataset (issue #17). The LLM finds, classifies, and extracts values with
verbatim source quotes; every calculation and consistency check is plain
Python.

## Status

Full pipeline (stages 1-7): classification, CLA extraction, deterministic
assessment, aggregation, cap-table/register/pool extraction, code
validation, and the versioned snapshot store.

## Usage

```bash
# via the command harness (agents):
python -m skills.harness /captable_build <startup> [--fresh]
# or the CLI:
python -m skills.captable_build build    --dataset <startup> [--fresh]
# or stage by stage:
python -m skills.captable_build classify  --dataset <startup>
python -m skills.captable_build extract   --dataset <startup>
python -m skills.captable_build assess    --dataset <startup>
python -m skills.captable_build aggregate --dataset <startup>
python -m skills.captable_build table     --dataset <startup>
python -m skills.captable_build snapshot  --dataset <startup>
```

`build` runs everything, reusing stored intermediate results only while
they are still fresh: every work product under `insights/captable/work/`
carries a `freshness` stamp (content hash of the parsed documents, hash
of the `config/captable/` files incl. the term checklist, model slug,
tool version) and a product whose stamp no longer matches is re-run
automatically — a newly added loan agreement, a corrected cap table, a
prompt edit or a model override never reuse outdated output. `--fresh`
discards every stored product regardless. `build` writes
`insights/captable/snapshots/<as_of>.json`,
`latest.json`, a table-only `captable.md`, and a deterministic visual
one-pager `captable.html` (re-render or add scenarios via
`python -m skills.captable_analysis render`). `assess` applies pure-Python
market-standard rules (bands in `config/captable/assessment_rules.json`).
`aggregate` groups identical-terms tranches for the 10/20 non-bank rules,
sums outstanding principal over executed loans only, supersedes term
sheets, flags expired maturities, and corroborates execution via
e-signature markers in the PDF streams. `table` extracts the current cap
table (group-aware, treasury/pool semantics), the share register (current
holdings for reconciliation), and ESOP/PSOP pool overviews. `snapshot`
validates everything in code (totals, the diluted = issued - treasury +
options/pools equation, register reconciliation, pool cross-document
consistency, nominal floor per art. 624 CO, CLA lifecycle,
cross-snapshot consistency) and stores the versioned snapshot.

`classify` labels every parsed document of the dataset (cap table vs
forecast model vs share register vs executed CLA vs term sheet, …) with an
as-of date, language, confidence, and rationale.

`extract` reuses the stored classification (or classifies first), then
extracts the SECA-derived term schema from every CLA document: lenders
(multi-lender agreements supported), principal, interest (mode, rate,
day-count, compounding, and the safe-harbor rate itself when the contract
quantifies it), maturity, conversion triggers (QEFR incl. its
new-investor minimum, change of control incl. repayment multiple,
maturity incl. a fixed maturity conversion price where the
conversion-price definition varies by trigger), cap/discount/floor,
denominator basis, subordination and its scope, MFN, pro-rata rights, and
the capital source for conversion shares. Every value carries a verbatim
quote that is verified against the parsed document text; absent terms are
reported in `missing_terms` with the sections that were scanned.

**The term list is a team-editable checklist**:
`config/captable/cla_terms.md` drives the extraction schema, the
per-term model guidance, quote verification, and missing-terms handling
— adding a term or refining guidance is a config edit, no code change
(the same pattern as `config/dd_checks/checklists/`). Fields the
pipeline computes on are guarded and cannot be removed or re-typed
without a loud load-time error. New terms appear in stored snapshots
after the next fresh extraction run.

Intermediate results are stored under the startup's
`insights/captable/work/` folder as JSON.

Note on `missing_terms` semantics: for presence-type booleans
(`mfn_clause`, `pro_rata_rights`, the trigger `*_present` fields) a value
of `false` is an ABSENCE CLAIM — "scanned, no such clause found" — and
therefore also appears in `missing_terms` with the sections scanned. This
is deliberate (the anti-laziness evidence contract), not a contradiction:
`false` states the conclusion, the `missing_terms` entry carries the
scan evidence for it.

## Requirements

The dataset must be synced (parsed Markdown present). Uses the configured
LLM via the services gateway; no Qdrant queries are needed for these two
stages.
`CLOUD_TPM_BUDGET` should be set in the local `.env` (see `.env-template`);
without it nothing paces Gemini traffic and a full build stampedes the
per-minute quota.

## Development & testing costs

Full builds on real data rooms cost real money (roughly USD 0.5-1.5 per
startup on gemini-3.5-flash, output/thinking tokens dominating). For
pipeline smoke tests use the synthetic fixture dataset and the cheap-model
override together:

```bash
# one-time install of the fixture dataset (see tests/fixtures/captable/):
mkdir -p "$LOCAL_STORAGE_PATH/storage/startups/synthcap/datasets"
cp tests/fixtures/captable/synthetic_*.md \
   "$LOCAL_STORAGE_PATH/storage/startups/synthcap/datasets/"
# then, after a dataset sync:
python -m skills.captable_build build --dataset synthcap \
    --model gemini/gemini-3.5-flash-lite --fresh
```

A full smoke build costs ~USD 0.01. `tests/fixtures/captable/
ground_truth.json` is the answer key (including two deliberately absent CLA
terms for the missing-terms recall check). Lite-model output is measurably
worse — never use `--model` overrides for real due-diligence output.

## Storage conventions

The analysis narrative (`captable_analysis`) is stored through the repo's
`InsightFile` convention (model-slug filename, manifest, freshness). The
snapshot store (`insights/captable/snapshots/<as_of>.json`, `latest.json`,
`captable.md`) deliberately does NOT use `InsightFile`: snapshots are
versioned by evidence date, not by generating model, and are consumed as
machine-readable inputs (by `captable_analysis` and, later, `sha_review`)
rather than as regenerable per-model insights.
