---
name: submission_ready
description: Screen Dealum applications in Application or Under review for completeness and initial eligibility, and draft an internal proposed action. Use for named submissions or a batch of in-scope applications.
---

# Submission ready

Produce an Ops screening report and proposed action for human review.

## Inputs and outputs

The async `submission_ready(startups=None)` accepts startup names or codes.
Omission processes in-scope applications. Named out-of-scope startups produce no
artifacts. On success, return a flat `list[InsightFile]`: checklist then response
for each startup. Canonical JSON audits remain internal; final Markdown artifacts
are timestamped.

## Workflow and dependencies

Select only Application and Under review. Named requests force a Dealum import;
automatic batches apply the six-hour per-startup gate and run sequentially.
Import preserves the prior snapshot until attachments have downloaded.
Synchronize before the checklist audit. No profile skill is a registry prerequisite.

Use `config/submission_ready/` for policy, questions, statuses and proposed actions.
The prompt restricts evidence to Dealum submissions; retrieval itself searches
the whole startup dataset. This is the accepted prompt-based restriction, not a
source filter. Business attractiveness and jury assessment are outside the task.

Run the checklist through [batch audit](../standards_and_architecture/SKILL.md#checklist-audits),
render its table, and generate a schema-validated action allowed for the current
stage. Missing or ambiguous evidence is Unclear; technical errors are failures.

Audit reuse follows indexed revisions and configuration. A stage-only change can
reuse the audit and create a new response; unrelated indexed changes can invalidate
it. Timestamped output reuse uses exact-model `is_reusable()`, with stage and
audit content in its key, rather than manual-first output selection.

## Side effects and failure behavior

Import Dealum data, synchronize, call models and save artifacts. Do not send
messages or change Dealum stages; humans decide on the proposed action.

Continue after individual startup failures. Successful artifacts and diagnostic
failure reports can remain saved, but any failure raises after processing;
failure reports are not appended to a returned partial-success list.

Known limitations: discovery/import/sync have a local three-attempt retry covering
all exceptions, including permanent failures. Other steps do not share that retry,
despite the broad failure wording. An “Older usable result” notice identifies
stored files without proving a complete, fresh prior run.

## Usage

```bash
conda run -n sictic-env python -m skills.harness /submission_ready
conda run -n sictic-env python -m skills.harness '/submission_ready "<STARTUP>"'
```

The direct CLI accepts repeated `--startup` options.

## References

- [Implementation](submission_ready.py)
- [Policy and configuration](../../config/submission_ready/)
- [Shared audit contract](../standards_and_architecture/SKILL.md#checklist-audits)
