---
name: dataroom_review
description: Assess an uploaded startup data-room dossier against SICTIC's published due-diligence document checklist. Use for ZIP or ephemeral dataset reviews.
---

# Data-room review

Assess the documents in a dataset against the published SICTIC due-diligence
checklist topics, using the same industry-aware chapter audits as
[dd_checks](../dd_checks/SKILL.md).

## Inputs and outputs

The async `dataroom_review(dataset_name)` accepts any existing dataset that
already holds the data-room files, including an uploaded ephemeral dataset. It
returns one Markdown report in `list[InsightFile]`.

There is no startup-name requirement and no Dealum import. A missing dataset
raises before any model call.

## Workflow and dependencies

Synchronize the dataset, then reuse a fresh report through
`InsightFile.find(selection="reusable")`. Freshness follows the indexed
revision, the shared `dd_checks` configuration, and structured-output
configuration.

On a cache miss, classify product type and run the configured DD chapters
through [assess_dd_dataset](../dd_checks/dd_checks.py). The published public
checklist
([Current SICTIC Due Diligence Checklist](https://www.sictic.ch/startup-resources/))
is the founder-facing inventory; the operational checklists in
`config/dd_checks/` expand those topics for evidence-based audit.

The skill is not in the bulk-refresh registry. It does not prepare a permanent
startup dossier.

## Side effects and failure behavior

Synchronization may convert and index documents. The review calls models and
saves chapter audits and the report. It sends nothing. Missing evidence is an
assessment outcome (`Not Found`), distinct from technical failure.

## Usage

```bash
conda run -n sictic-env python -m skills.harness '/dataroom_review "<DATASET>"'
conda run -n sictic-env python -m skills.dataroom_review --dataset "<DATASET>"
```

## References

- [Implementation](dataroom_review.py)
- [DD checks engine](../dd_checks/SKILL.md)
- [Published checklist](https://www.sictic.ch/startup-resources/)
