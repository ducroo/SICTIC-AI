---
name: submission_ready
description: Screen named Dealum applications at any stage, or automatically select Application and Under review submissions, for completeness and initial eligibility.
---

# Submission ready

Produce an Ops screening report and proposed action for human review.

## Inputs and outputs

The async `submission_ready(startups=None)` accepts startup names or codes.
Omission processes Application and Under review applications. Explicit names or
codes run at any stage, including an unknown stage. On success, return a flat
`list[InsightFile]`: checklist then response
for each startup. Canonical JSON audits remain internal; final Markdown artifacts
are timestamped.

## Workflow and dependencies

Automatic batches select only Application and Under review. Named requests
ignore the stage filter and force a Dealum import;
automatic batches apply the six-hour per-startup gate and run sequentially.
Within bulk refresh, reuse that run's application snapshot and successful import
instead of acquiring the same submission twice. Standalone named calls still import.
Import preserves the prior snapshot until attachments have downloaded.
Synchronize before the checklist audit. No profile skill is a registry prerequisite.

Use `config/submission_ready/` for policy, questions, statuses and proposed actions.
The prompt restricts evidence to Dealum submissions; retrieval itself searches
the whole startup dataset. This is the accepted prompt-based restriction, not a
source filter. Business attractiveness and jury assessment are outside the task.

Run the checklist through [batch audit](../standards_and_architecture/SKILL.md#checklist-audits),
render its table, and generate a schema-validated action allowed for the current
stage. Missing or ambiguous evidence is Unclear; technical errors are failures.

The response separates **Eligibility concerns** from **Missing or inconsistent
information**. Confirmed wrong geography is an eligibility concern; missing or
ambiguous evidence is not confirmed ineligibility. The proposed-action field
remains limited to progression or sending concerns for Application and Under review.
At other or unknown stages, the schema permits only `Assessment only`: report
findings without recommending a stage transition or outreach.
The skill does not propose an additional rejection action. Consolidate duplicate
concerns and do not block progression solely for missing optional routing details.

Audit reuse follows indexed revisions and configuration. A stage-only change can
reuse the audit and create a new response; unrelated indexed changes can invalidate
it. Timestamped output reuse uses exact-model `is_reusable()`, with stage and
audit content in its key, rather than manual-first output selection.

The skill supplies `audit_response_schema.json` to the engine. Assessment fields
and status values are schema-defined; results are nested under `result` in the
version-2 audit artifact, with technical errors recorded separately.

The action schema enforces stage-specific actions and nonblank rationales.
The business reviewer trims text, drops blank concerns, and checks that sending
concerns has at least one concern. Eight concerns is prompt guidance only;
neither the schema nor the reviewer imposes a count limit.
Rendering consumes the accepted result without repeating those checks.

## Side effects and failure behavior

Import Dealum data, synchronize, call models and save artifacts. Do not send
messages or change Dealum stages; humans decide on the proposed action.
`proposed_action(report)` and `stated_concerns(report)` read the action and the
two concern lists back from a rendered response for
[application_feedback](../application_feedback/SKILL.md), which drafts
feedback emails for applications with concerns.

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

The direct CLI accepts repeated `--startups` options; `--startup` remains an alias.
The harness accepts multiple positional `startups` separated by spaces.

## References

- [Implementation](submission_ready.py)
- [Policy and configuration](../../config/submission_ready/)
- [Shared audit contract](../standards_and_architecture/SKILL.md#checklist-audits)
