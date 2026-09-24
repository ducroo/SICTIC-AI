---
name: cla_review
description: Review one convertible-loan term sheet from the lender's side, against the SECA CLA model term sheets and in the context of the startup's cap table, existing loans and SHA. Use before SICTIC members lend.
---

# CLA term sheet review

Identify the term sheet, extract its terms, judge them for a lender and show what they do in this company.

## Inputs and outputs

The async `cla_review(dataset_name, *, document=None, ticket=None, fresh=False)`
returns one Markdown report in `list[InsightFile]`, named
`cla-review-<startup>-<document>-<model>.md`, one per reviewed document. JSON
intermediates (`identification`, `extraction`, `assessment`, `conversion`,
`loan-context`, `sha-context`, `audits/<checklist>`) live under
`insights/cla-review/` and carry the document identity in their identifier.
`document` names the data-room path of the term sheet; omitted, the model
selects the most recent CLA term sheet and executed loans are context, not
candidates. `ticket` is the member's own amount and is part of the
configuration key, so a new ticket replaces the generated result for that
document. `fresh` bypasses generated reuse without deleting files or
overriding manual inputs.

**Slices:** slice 0 (contract, rules, references, fixture), slice 1
(question 1: identify, extract, company- and lender-angle assessment) and
slice 2 (question 2, deterministic part: my conversion, the existing loans,
10/20 before and after) are built; the audits against the SECA term sheets,
the SHA context and the synthesis are listed in the report as pending. The
slices are defined in
[docs/cla-review-design.md](../../docs/cla-review-design.md#7-slices).

JSON intermediates per document: `identification`, `extraction`,
`assessment`, `conversion`, `loan-context`.

Artifact identity is the slugified full relative path of the document, so
equal basenames in different folders stay distinct. The automatic
identification is one dataset-level artifact (`identification-automatic`);
an explicit `document` gets its own (`<document>-identification`), so the
two never reuse each other. The report is
`cla-review-<startup>-<document>-<model>.md` directly under `insights/`.

## Workflow and dependencies

Prepare and synchronize the startup. Identify the term sheet: an explicit
`document` is resolved through the shared document-path resolution at the
configured minimum score; otherwise the model selects the most recent CLA
term sheet or draft from three retrieval queries, executed loans being
context and never candidates, and only the selected path is resolved. An
existing `captable_build` classification, when present, seeds candidates
and exclusions and is part of the identification key.

Extract the selected document with the shared `captable_build` CLA
checklist (`config/captable_build/cla_terms.md`, including its term-sheet
provisions group); every value carries a verbatim quote and every absence a
`missing_terms` entry. Assess it twice: `assess_cla` with the
`captable_build` bands (company angle) and `lib.cla_review.assessment`
with `config/cla_review/settings.json` (lender angle). Every lender rule
carries value, source, status, effective date and an `active` flag; only
`approved` rules may be active and judge, an inactive rule yields an open
question with the observation, a rule whose input is unavailable is not
evaluated and names the input. The term in months is measured from the
run date, which is part of the assessment key.

Each stage is a managed JSON artifact validated on read and write against
`config/cla_review/artifact_schemas.json` or the `captable_build` CLA
schema; a stage reuses its artifact when the configuration and the
upstream artifact are unchanged. Manual files win, `fresh` bypasses
generated reuse only, failures are never saved. `ticket` is part of the
report key so a new ticket regenerates the report for the same document
without regenerating the extraction.

Question 2 reads the consolidated `captable_build` snapshot through
`lib.captable.insights.select_consolidated`; it is never generated here and
the registry declares no prerequisite. Its state is part of the conversion
and loan-context keys: `reusable` (content keyed), `absent` or `stale`.
`lib.cla_review.conversion` resolves and labels every input before any
number (ticket: given, else the aggregate amount divided by the configured
member count as a stated assumption; round size: the qualified-financing
minimum; denominator, interest, currency, nominal value, valuation grid
from the cap or `valuation_grid_absolute`), omits a calculation whose
input is missing with the reason, and prices the ticket at every grid
point and conversion date through `lib.captable.model` next to the existing
loans (`lib.captable.notes`) and the other new lenders. `lib.cla_review.loans`
puts the term sheet next to every executed loan, reads the MFN effect both
ways, checks identical-terms membership and counts the 10/20 rules before
and after N members through `aggregate_clas` on a synthetic executed copy.

## Side effects and failure behavior

Preparation may import, convert and index documents. The review calls models
and saves intermediates and the report; it sends nothing. An absent or stale
cap-table snapshot yields an insufficient-evidence paragraph for question 2
and the run completes; a malformed snapshot, failed path resolution and
technical failures remain errors. No plausible term sheet, an unresolvable path or an extraction
failure stops the run without saving a partial artifact. The report aids human
review and is not legal advice.

## Usage

```bash
conda run -n sictic-env python -m skills.harness '/cla_review "<STARTUP>"'
conda run -n sictic-env python -m skills.harness -- /cla_review "<STARTUP>" --document "legal/cla-term-sheet.pdf" --ticket 25000
conda run -n sictic-env python -m skills.cla_review --startup "<STARTUP>" --document "legal/cla-term-sheet.pdf" --ticket 25000 --fresh
```

The direct CLI uses `--startup`; `--dataset` and `-d` remain compatibility aliases.

## References

- [Implementation](cla_review.py)
- [Design and slices](../../docs/cla-review-design.md)
- [Configuration, rules and SECA reference term sheets](../../config/cla_review/)
- [Shared CLA extraction checklist](../../config/captable_build/cla_terms.md)
- [Shared audit contract](../standards_and_architecture/SKILL.md#checklist-audits)
