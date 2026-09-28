---
name: pitch_deck_review
description: Review a startup pitch deck against SICTIC's published jury criteria and investment criteria. Use when a founder or an operator wants a document check of one deck.
---

# Pitch deck review

Read one dataset's pitch deck and report how it sits against the published SICTIC criteria.

## Inputs and outputs

The async `pitch_deck_review(dataset_name)` accepts any existing dataset that contains the deck, including an uploaded ephemeral dataset. It returns one Markdown report in `list[InsightFile]`. The canonical JSON audit stays internal.

There is no startup-name requirement and no Dealum import. A missing dataset raises `FileNotFoundError` before any model call.

## Workflow and dependencies

Synchronize the dataset, then reuse a fresh report through `InsightFile.find(selection="reusable")`. Freshness follows the indexed revision, this skill's configuration, and structured-output configuration.

On a cache miss, run the single checklist in `config/pitch_deck_review/` through [batch audit](../standards_and_architecture/SKILL.md#checklist-audits). The checklist covers the four published jury criteria (business potential, product innovation, team potential, document quality) and the published investment criteria. The wording of the investment checks matches [the screening policy](../../config/submission_ready/policy.md), which cites https://www.sictic.ch/startups/. Whether a founder submitted the application themselves is a channel fact, not a deck fact, so that policy bullet is not a check.

`audit_response_schema.json` defines the status enum. `audit_instructions.md` defines the missing-evidence policy. Render the validated audit with `json_to_markdown_table` and save it under a short status legend. There is no second synthesis call.

The skill is not in the bulk-refresh registry. A deck review does not prepare a data room and does not run profile skills.

## Side effects and failure behavior

Synchronization may convert and index the deck. The review calls models and saves the audit and the report. It sends nothing and does not change an application stage.

A technical audit failure raises before the Markdown report is saved. Missing evidence is `Not Found`, which is a completed assessment. A cached report is returned before the audit is read, so editing the JSON audit alone does not refresh the report.

This is a document check. It is not a jury decision.

## Usage

```bash
conda run -n sictic-env python -m skills.harness '/pitch_deck_review "<DATASET>"'
conda run -n sictic-env python -m skills.pitch_deck_review --dataset "<DATASET>"
```

The harness command takes one dataset name. The direct CLI uses `--dataset`.

## References

- [Implementation](pitch_deck_review.py)
- [Checklist, instructions, and schema](../../config/pitch_deck_review/)
- [Published criteria as used for screening](../../config/submission_ready/policy.md)
- [Shared audit contract](../standards_and_architecture/SKILL.md#checklist-audits)
