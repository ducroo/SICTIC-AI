---
name: dd_checks
description: Assess a startup data room against product-type-aware due-diligence checklists and produce one complete report. Use for comprehensive checklist review.
---

# DD checks

Assess the configured due-diligence chapters and combine their findings.

## Inputs and outputs

The async `dd_checks(startup)` returns one final Markdown report in
`list[InsightFile]`, named `dd-checks-<startup>-<model>.md`.
Canonical chapter JSON audits remain internal.

The report states the product type, then lists the most important findings
under `## Most important findings`, then the complete chapter tables.
`most_important_findings(report)` returns that section for
[dd_priorities](../dd_priorities/SKILL.md), or `None` when a report, such as a
manual one, has none.

## Workflow and dependencies

Prepare the startup through `ensure_startup_dataset` and synchronize before
assessment. Classify product type with the configured JSON schema; select each
chapter's matching variant or its general fallback. Product has biology,
hardware and software variants plus a general fallback.

This is the sole owner of the Software/Hardware/Biology/General classification;
it does not consume product type from startup_sector. Existing internal
`industry_type` keys, classifier entry points, `industry_focus/` and checklist
filenames remain unchanged for compatibility. Missing evidence retains the
existing logged general-checklist fallback; it is not affirmative evidence
that the startup has a General product type.

Run selected checklists concurrently through
[the shared audit engine](../standards_and_architecture/SKILL.md#checklist-audits).
Every check receives the audit instructions plus a startup context: the
product type and that type's text from `config/dd_checks/industry_focus/`,
which says what matters most for such startups. The context holds only these
configured values, because a changing text would invalidate every cached
chapter audit. Each check returns an importance from 1 to 10 next to its
status.

Render the most important findings with `ranked_checks_to_markdown_table`:
checks with at least the configured minimum importance, highest first, up to
the configured maximum count (`settings.json`). Equal values keep checklist
order. Render the complete chapter tables with `json_to_markdown_table`; there
is no synthesis model call. Checklists, classification, product-type texts and
statuses belong to `config/dd_checks/`. `audit_response_schema.json` defines
the fields, status enum and importance range; `audit_instructions.md` defines
the evidence policy and the importance scale.

The registry declares `startup-profile` as a prerequisite. Direct DD neither
requests nor consumes that profile. After synchronization, select a manual or
reusable final report through `InsightFile.find(selection="reusable")`, using
DD and structured-output configuration and the indexed dataset revision. Return
it before product-type classification or chapter audits. On a cache miss, classify
product type and assemble the final report, reusing eligible chapter audits.
Chapter audits include the product-type context, so they are reused only when the
classification matches the one they were made with.

Product-type generation delegates technical checks to its schema and uses a business
reviewer to require evidence for a selected product type. Result processing only
maps the accepted classification or applies the existing general fallback.
The standalone text parser explicitly uses the shared repair and validation
functions followed by the same business reviewer.

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
