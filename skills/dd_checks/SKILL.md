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

## Engines

`engine` in `config/dd_checks/settings.json` selects who writes the checks:

- `agent` (default): an agent reads the data room, assesses every check and
  also writes the DD priorities, `dd-priorities-<startup>-<model>.md`. A pilot
  on four startups rated its priorities the same or better than the pipeline's;
  see the [pilot review](../../docs/reviews/dd-agent-pilot-2026-11-18.md).
- `pipeline`: the earlier workflow with retrieval, one model call per check and
  a separate priorities synthesis in `dd_priorities`. It stays as a fallback
  until the agent has run in production for a few weeks.

The engine setting applies only to `dd_checks`.
[dataroom_review](../dataroom_review/SKILL.md) always uses the pipeline through
`assess_dd_dataset`, for uploaded data rooms without Dealum. Its server runs a
local model whose context is too small for the agent.

Both engines use the same checklists, product types, `industry_focus`, audit
instructions, result schema and report format, and save the chapter audits as
`batch-audit/dd-checks-<checklist>-<model>.json`.

## Workflow and dependencies

Prepare the startup through `ensure_startup_dataset` and synchronize before
assessment. Product has biology, hardware and software checklist variants plus
a general fallback; each chapter uses its product-type variant or the general
one.

This is the sole owner of the Software/Hardware/Biology/General classification;
it does not consume product type from startup_sector. Existing internal
`industry_type` keys, classifier entry points, `industry_focus/` and checklist
filenames remain unchanged for compatibility.

Every check receives the audit instructions plus a startup context: the
product type and that type's text from `config/dd_checks/industry_focus/`,
which says what matters most for such startups. Each check returns an
importance from 1 to 10 next to its status.

Render the most important findings with `ranked_checks_to_markdown_table`:
checks with at least the configured minimum importance, highest first, up to
the configured maximum count (`settings.json`). Equal values keep checklist
order. Render the complete chapter tables with `json_to_markdown_table`.
Checklists, classification, product-type texts and statuses belong to
`config/dd_checks/`. `audit_response_schema.json` defines the fields, status
enum and importance range; `audit_instructions.md` defines the evidence policy
and the importance scale.

The registry declares `startup-profile` as a prerequisite. Direct DD neither
requests nor consumes that profile.

### Agent

After synchronization, a manual report is returned as it is. A generated report
is reused while it and the priorities match the configuration (`dd_checks` and
the priorities format of `dd_priorities`) and the indexed dataset revision.
Otherwise the OpenAI Agents SDK runs two agents with the configured model
through LiteLLM:

- The main agent decides the product type with the classification rules in
  `industry_type_llm_instructions.md`, calls the checklist agent once per
  checklist, checks the questions that could change its conclusions against
  the documents, and submits the priorities in the format of
  `config/dd_priorities/llm_instructions.md`. Each priority also gets a
  `**Verified:**` line that says what the agent checked in the documents.
- The checklist agent assesses and records every check of one checklist.

The workflow instructions are `agent_instructions.md` and
`agent_chapter_instructions.md`; the limits are under `agent` in
`settings.json`. The tools only reach the startup's current parsed documents:
`list_documents`, `read_document` (by page), `search_text` (text or regular
expression, no Qdrant), `get_checklists`, `get_checklist`, `record_check`,
`recorded_checks` and `submit_priorities`. `record_check` validates each result
against the audit result schema and rejects unknown check numbers; checklist
selection and numbering are those of the pipeline.

### Pipeline

`assess_dd_dataset` runs the pipeline on a prepared dataset. After
synchronization, select a manual or reusable final report through
`InsightFile.find(selection="reusable")`, using DD and structured-output
configuration and the indexed dataset revision. Return it before product-type
classification or chapter audits. On a cache miss, classify the product type
with the configured JSON schema and assemble the final report, reusing eligible
chapter audits. Chapter audits include the product-type context, so they are
reused only when the classification matches the one they were made with.
Missing classification evidence retains the existing logged general-checklist
fallback; it is not affirmative evidence that the startup has a General
product type.

Run selected checklists concurrently through
[the shared audit engine](../standards_and_architecture/SKILL.md#checklist-audits).
The startup context holds only configured values, because a changing text
would invalidate every cached chapter audit. There is no synthesis model call.

Product-type generation delegates technical checks to its schema and uses a business
reviewer to require evidence for a selected product type. Result processing only
maps the accepted classification or applies the existing general fallback.
The standalone text parser explicitly uses the shared repair and validation
functions followed by the same business reviewer.

## Side effects and failure behavior

Preparation may import Dealum documents; synchronization may convert and index
data. Model calls and insight saves occur; there is no outreach. Missing
evidence is an assessment outcome, distinct from technical failure.

The agent sends the documents it reads to the configured model provider, often
a large part of the data room; SDK tracing is disabled. Its model calls wait
for the shared scheduler like `generate_*`, so parallel runs stay within
`CLOUD_TPM_BUDGET`. A model call that takes longer than
`request_timeout_seconds` is cancelled; raise this limit for a slow local
model. Rate limits, timeouts and short provider outages are retried up to six
times with increasing waits. The run stops at the turn limits and when its
tokens exceed `max_total_tokens`. When the agent does not finish,
it is asked once more; if checks or priorities are still missing, the run
raises and saves nothing. The token usage is logged also for a failed run.

In the pipeline, per-check retrieval may index data. Wait for all chapter
outcomes. Any chapter failure raises before a new final Markdown report is
saved; successful chapter JSON artifacts can remain saved and reusable. A
partial final report is not returned.

## Usage

```bash
conda run -n sictic-env python -m skills.harness '/dd_checks "<STARTUP>"'
```

The direct CLI uses `--startup`. The OpenAI Agents SDK (`openai-agents`) is in
`environment.yml`; update an existing environment with
`conda env update -f environment.yml`.

## References

- [Implementation](dd_checks.py), [agent](agent.py), [agent wiring](agent_runner.py)
- [Configuration and checklists](../../config/dd_checks/)
- [Shared audit contract](../standards_and_architecture/SKILL.md#checklist-audits)
