---
name: dd_priorities
description: Synthesizes an existing dd_checks report into up to eight distinct, decision-relevant due-diligence priorities for a buy-side DD team. Use when a startup's comprehensive DD checklist has already been generated and the user wants the most material concerns, missing information, supporting evidence, and follow-up actions.
---

# DD Priorities

Turn a saved `dd_checks` report into a concise, prioritized DD report without
rerunning the checklist or searching the source dataset.

## Workflow

1. Resolve the startup's saved `dd_checks` insight.
2. Stop with a clear instruction to run `dd_checks` when no report exists.
3. Pass the complete report to one synthesis call using
   `config/dd_priorities/llm_instructions.md`.
4. Save the result as a separate `dd_priorities` insight and return its path.
5. Reuse an existing result when both the source dataset and synthesis input are
   unchanged.

The synthesis must return up to eight non-overlapping concerns. Preserve
supporting checklist IDs and citations already present in `dd_checks`. Do not
use the ranking library or perform additional semantic searches.

## Usage

```bash
conda run -n sictic-env python -m skills.harness /dd_priorities "<STARTUP_NAME>"
```
