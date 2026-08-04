---
name: dd_checks_agent
description: Agent-orchestrated version of dd_checks. Performs a comprehensive M&A-style due diligence review of a startup's data room using the same predefined, industry-aware checklists as dd_checks, but with the invoking Claude Code agent itself doing the industry classification and per-chapter evaluation — via one subagent per DD chapter — instead of calling out to litellm. Use when the operator has a Claude subscription but no separate LLM_API_KEY configured for this repo, or when explicitly asked to run dd_checks in agent-orchestrated / no-API-key mode.
---

# M&A Due Diligence Checklist — Agent-Orchestrated Mode

## Mode

This is the **agent-orchestrated mode** of `dd_checks` (Constitution Principle II — Dual-Mode LLM
Execution). Unlike `skills/dd_checks`, which runs unattended and calls `litellm.completion()`
(via `dataset_chat` / `batch_audit`) against a configured `LLM_API_KEY`, this skill is executed
directly by **you**, the invoking Claude Code agent, reading the data room's parsed Markdown and
reasoning over it yourself. No `LLM_API_KEY` and no local text-generation model are required.

Instead of one long single-pass analysis, this skill dispatches **one subagent per DD chapter**,
run in parallel via the `Agent` tool. This is deliberate, for two reasons:

1. **Context window:** a data room can be large; splitting the checklist evaluation by chapter
   keeps each subagent's reading task bounded instead of forcing the entire data room and every
   checklist into one context window.
2. **Resiliency:** if one chapter's subagent fails or errors, that failure is caught and reported
   inline for that chapter only — it must not sink the rest of the report, matching the existing
   per-chapter resiliency behavior of `skills/dd_checks`.

Do **not** call `skills.dataset_chat` or `skills.batch_audit` anywhere in this workflow — those
stay on their existing `litellm` path for unattended/batch callers and are untouched by this mode.
Do not import or call `litellm` from any code you run as part of this skill.

## Trigger

Use this skill when asked to run dd_checks (or a due-diligence checklist review) for a startup in
**agent-orchestrated** or **no-API-key** mode — e.g. "Run dd_checks_agent for Avientus" or "Run the
agent-orchestrated DD checks for &lt;dataset&gt;".

## Inputs

You will be given a startup name or dataset identifier. Resolve it to the dataset slug used for
storage paths:

```python
from lib.slugify import slugify
dataset = slugify(startup_name)
```

All steps below use this `dataset` slug.

## Workflow

### 1. Verify the dataset exists

This skill does not fetch or import data room files from any external source (no Dealum sync, no
Google Drive sync). Confirm the raw data room is already present:

```python
from lib.storage import get_storage
from lib.datasets.paths import dataset_raw_path

storage = get_storage()
raw_path = dataset_raw_path(dataset)
if not storage.exists(raw_path):
    raise ValueError(f"Dataset for {dataset} not found at {raw_path}.")
```

If it does not exist, stop and tell the user the dataset must be ingested first — do not attempt
to create or download one.

### 2. Reconcile conversions (Docling-only, no LLM/embedding call)

Ensure the raw source files have durable parsed Markdown counterparts. This step only runs Docling
extraction — it does not embed or index anything, and does not call any LLM:

```python
from lib.datasets.paths import dataset_raw_path, dataset_parsed_path
from lib.datasets.conversion import reconcile_conversions

await reconcile_conversions(dataset, dataset_raw_path(dataset), dataset_parsed_path(dataset))
```

### 3. Determine the industry type yourself

Do **not** call `dataset_chat`. Instead:

1. Read `config/dd_checks/industry_type_query.md` — what to look for.
2. Read `config/dd_checks/industry_type_llm_instructions.md` — the classification definitions
   (Software / Hardware / Biology / General), decision rules, and required output format.
3. Read the parsed data room yourself, directly, under
   `lib.datasets.paths.dataset_parsed_path(dataset)` (use `Read`/`Glob`/`Grep` on that directory
   tree — it is durable Markdown, not raw source files). Look specifically for direct, company-
   specific descriptions of the product/technology/business model, per the query file.
4. Apply the classification decision rules from `industry_type_llm_instructions.md` yourself and
   produce the same `Industry Type: TYPE` output format it specifies.
5. Normalize the result to lowercase to get `industry_type` (one of `software`, `hardware`,
   `biology`, `general`). If the evidence is insufficient (the instructions say to output
   `INSUFFICIENT_CONTEXT`) or the result doesn't cleanly map to one of the four types, default
   `industry_type` to `general` — this mirrors the fallback behavior of the existing `dd_checks`
   skill's `parse_industry_type`.

### 4. Resolve the checklist file per chapter

1. List the files in `config/dd_checks/checklists/`. Each filename has the form
   `<chapter>_<industry_type>.md` (e.g. `7_product_software.md` → chapter `7_product`, industry
   type `software`; `4_financials_general.md` → chapter `4_financials`, industry type `general`).
2. Derive the distinct set of chapters by stripping the trailing `_<industry_type>` segment from
   every filename.
3. For each chapter, in filename order, select its checklist file:
   - Prefer `<chapter>_<industry_type>.md`, using the `industry_type` resolved in workflow
     step 3 ("Determine the industry type yourself") above, if that file exists.
   - Otherwise fall back to `<chapter>_general.md` if it exists.
   - Otherwise skip that chapter entirely (no checklist applies).

This mirrors the selection logic in `skills/dd_checks/SKILL.md` and `skills/dd_checks/dd_checks.py`
(`chapter_by_chapter`).

### 5. Dispatch one subagent per applicable chapter, in parallel

For each chapter resolved in step 4, launch one subagent via the `Agent` tool. Launch **all** of
them in the same response (multiple `Agent` tool calls in one turn) so they run in parallel — they
are fully independent of each other.

Each subagent's brief must include, verbatim:

- The dataset slug (`dataset`), and that the parsed data room lives under
  `lib.datasets.paths.dataset_parsed_path(dataset)` and should be read directly with `Read`/`Grep`
  (this is a research task, not a coding task — no edits).
- The full, verbatim content of that chapter's selected checklist `.md` file (from step 4).
- The exact evaluation instructions and output format below.

**Subagent evaluation instructions (include verbatim in each subagent's prompt):**

> For every checklist item (each `*` bullet under any `##`/`#` heading in the checklist above),
> search the dataset's parsed Markdown for evidence and classify it as exactly one of:
>
> - **Pass** — the data room contains clear, sufficient evidence that the item is satisfied.
> - **Fail** — the data room contains clear evidence that the item is *not* satisfied, or explicitly
>   contradicts it.
> - **Unclear** — evidence is missing, incomplete, ambiguous, or conflicting. Never guess a Pass or
>   Fail when you are not sure — default to Unclear.
>
> For every item, cite the evidence: name the source document/file and quote or closely paraphrase
> the specific excerpt that supports your verdict. For **Unclear**, state exactly what is missing,
> ambiguous, or conflicting instead of a supporting quote.
>
> Return your findings as a single Markdown section, formatted exactly as follows (repeat the table
> per `##` subsection of the checklist if the checklist has them; otherwise use one table for the
> whole chapter):
>
> ```
> ## Chapter: <chapter title from the checklist's top-level `#` heading, without the leading number>
>
> ### <subsection title, only if the checklist has `##` subsections — omit this line otherwise>
>
> | # | Item | Status | Evidence |
> |---|---|---|---|
> | 1 | <short item name> | Pass | (document-name.md): "<quoted excerpt>" |
> | 2 | <short item name> | Unclear | Missing: no document addresses <what's missing> |
> ```
>
> Number items sequentially starting at 1 within each table. Do not omit any checklist item. Return
> only this Markdown section — no preamble, no closing commentary.

### 6. Handle per-chapter failures without losing the report

If a chapter's subagent errors, times out, or returns something you cannot use as a valid section
(e.g. it reports it was unable to complete), catch that and substitute this section instead of
omitting the chapter:

```
## Chapter: <chapter title>

**Error:** chapter failed: <short reason>
```

This matches the existing per-chapter resiliency behavior of `skills/dd_checks` — one chapter
failing must never prevent the rest of the report from being assembled and saved.

### 7. Assemble the consolidated report

Concatenate all chapter sections (successes and failure notes alike), in the same chapter order
used for dispatch, into one Markdown document:

```
# M&A Due Diligence Checks for <dataset> (Agent-Orchestrated)

**Industry Type:** <industry_type>

<chapter section 1>

<chapter section 2>

...
```

### 8. Persist the report

Write the assembled Markdown to a temporary file, then persist it as an insight via the save
helper (the *only* supported way to save this report — do not hand-construct insight paths):

```bash
conda run -n sictic-env python -m skills.dd_checks_agent.save_report "<dataset>" --content-file <path-to-written-report>
```

This calls `InsightFile(dataset=dataset, skill="dd_checks", model="anthropic/claude-code-agent",
prompt_key="dd_checks_agent-v1").save(content)` and prints the resulting `insight.path`. The
`anthropic/claude-code-agent` model tag keeps this report's filename distinct from — and never
colliding with — a litellm-generated `dd_checks` report for the same dataset.

### 9. Report back

Tell the user the due diligence review is complete and report the exact `insight.path` printed by
`save_report`.

## Usage

This skill has no standalone CLI entry point for the full workflow — the workflow above **is** the
skill, executed by you as the invoking agent. Trigger it with a natural-language request, e.g.:

```
Run dd_checks_agent for "<STARTUP_NAME>"
```

Only the final persistence step is a script:

```bash
conda run -n sictic-env python -m skills.dd_checks_agent.save_report "<dataset>" --content-file <path>
```
