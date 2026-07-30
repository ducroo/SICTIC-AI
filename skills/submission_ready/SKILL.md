---
name: submission_ready
description: Screens Dealum applications in the Application or Under review stage for completeness and SICTIC initial eligibility, then drafts an internal proposed action for Ops. Use for one or more named startups or an overnight batch of all in-scope submissions.
---

# Submission Ready

Review only the startup's Dealum application and documents submitted through
Dealum. Do not use separately scraped website or LinkedIn content as evidence.

## Workflow

1. Retrieve Dealum applications and keep only `Application` and
   `Under review`. A named out-of-scope startup produces no artifacts.
2. With named startups, force a fresh Dealum import. Without names, process
   all in-scope applications sequentially using the six-hour per-startup gate.
3. Replace the Dealum snapshot only after all attachments download.
4. Reuse a fresh checklist when substantive submission content is unchanged.
   A stage-only change creates a new response without rerunning the checklist.
5. Load the policy, checklist, output schema, and table header from
   `config/submission_ready/`.
6. Run every checklist item independently against the dataset.
7. Use `Unclear` whenever the submitted evidence is missing, ambiguous,
   conflicting, or not retrievable. Never infer a pass or fail.
8. Save a timestamped checklist and internal proposed action through
   `InsightFile`. Humans decide whether to contact the startup or change its
   Dealum stage; the skill does neither.

The result is an Ops screening report, not a jury assessment. Do not evaluate
business attractiveness, pitch quality, or investment readiness.

## Usage

```bash
conda run -n sictic-env python -m skills.harness /submission_ready
conda run -n sictic-env python -m skills.harness /submission_ready "<STARTUP_NAME>"
```
