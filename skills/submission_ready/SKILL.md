---
name: submission_ready
description: Checks whether a startup's Dealum funding application is complete and meets SICTIC's initial eligibility criteria. Use for Ops screening before an application enters the Jury funnel; it returns an evidence-based Pass, Fail, or Unclear table without assessing pitch readiness or investment quality.
---

# Submission Ready

Review only the startup's Dealum application and documents submitted through
Dealum. Do not use separately scraped website or LinkedIn content as evidence.

## Workflow

1. Resolve and synchronize the startup dataset.
2. Load the policy, checklist, output schema, and table header from
   `config/submission_ready/`.
3. Run every checklist item independently against the dataset.
4. Use `Unclear` whenever the submitted evidence is missing, ambiguous,
   conflicting, or not retrievable. Never infer a pass or fail.
5. Save one report through `InsightFile` under the startup's insights.

The result is an Ops screening report, not a jury assessment. Do not evaluate
business attractiveness, pitch quality, or investment readiness.

## Usage

```bash
conda run -n sictic-env python -m skills.harness /submission_ready "<STARTUP_NAME>"
```
