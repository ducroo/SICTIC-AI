---
name: dd_checks
description: Assess a startup data room against industry-aware due-diligence checklists and produce one complete report. Use for comprehensive checklist review.
---

# DD checks

Assess the configured due-diligence chapters and combine their findings.

## Inputs and outputs

The async `dd_checks(startup)` returns one final Markdown report in
`list[InsightFile]`, named `dd-checks-<startup>-<model>.md`.
Canonical chapter JSON audits remain internal.

## Workflow and dependencies

Prepare the startup through `ensure_startup_dataset` and synchronize before
assessment. Classify industry with the configured JSON schema; select each
chapter's matching variant or its general fallback. Product has biology,
hardware and software variants plus a general fallback.

Run selected checklists concurrently through
[the shared audit engine](../standards_and_architecture/SKILL.md#checklist-audits).
Render validated results with `json_to_markdown_table`; there is no synthesis
model call. Checklists, classification and statuses belong to
`config/dd_checks/`.

The registry declares `startup-profile` as a prerequisite. Direct DD neither
requests nor consumes that profile. Each invocation reruns classification and
assembles the final table, reusing eligible chapter audits. The final report
records DD, batch-audit and structured-output configuration, but is not selected
through a final-output cache lookup or manual-output lookup.

## Side effects and failure behavior

Preparation may import Dealum documents; synchronization and per-check retrieval
may convert and index data. Model calls and insight saves occur; there is no
outreach. Missing evidence is an assessment outcome, distinct from technical
failure.

Wait for all chapter outcomes. Any chapter failure raises before a new final
Markdown report is saved; successful chapter JSON artifacts can remain saved
and reusable. A partial final report is not returned.

## Usage

```bash
conda run -n sictic-env python -m skills.harness '/dd_checks "<STARTUP>"'
```

The direct CLI uses `--startup`.

## References

- [Implementation](dd_checks.py)
- [Configuration and checklists](../../config/dd_checks/)
- [Shared audit contract](../standards_and_architecture/SKILL.md#checklist-audits)
