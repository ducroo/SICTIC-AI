# captable_build

Builds structured cap-table and convertible-loan facts for one startup
dataset (issue #17). The LLM finds, classifies, and extracts values with
verbatim source quotes; every calculation and consistency check is plain
Python.

## Status

Slice 1: document classification (stage 1) and CLA term extraction
(stage 2). Later slices add the qualitative SECA checklist, multi-CLA
aggregation, cap-table extraction, code validation, and the versioned
snapshot store under `insights/captable/snapshots/`.

## Usage

```bash
python -m skills.captable_build classify --dataset <startup>
python -m skills.captable_build extract  --dataset <startup>
```

`classify` labels every parsed document of the dataset (cap table vs
forecast model vs share register vs executed CLA vs term sheet, …) with an
as-of date, language, confidence, and rationale.

`extract` reuses the stored classification (or classifies first), then
extracts the SECA-derived term schema from every CLA document: lenders
(multi-lender agreements supported), principal, interest (mode, rate,
day-count, compounding), maturity, conversion triggers, cap/discount/floor,
denominator basis, subordination and its scope, MFN, pro-rata rights, and
the capital source for conversion shares. Every value carries a verbatim
quote that is verified against the parsed document text; absent terms are
reported in `missing_terms` with the sections that were scanned.

Intermediate results are stored under the startup's
`insights/captable/work/` folder as JSON.

## Requirements

The dataset must be synced (parsed Markdown present). Uses the configured
LLM via the services gateway; no Qdrant queries are needed for these two
stages.
