---
name: captable
description: Produce a Markdown capitalization report with deterministic ownership and conversion tables over consolidated captable_build data.
---

# captable

## Inputs and outputs

One startup dataset slug and optional hypothetical round inputs (`pre_money`,
`investment`, `fx_rates`, `currency`). Returns one Markdown `InsightFile` in a
flat list, directly under `insights/`, with the standard `captable` filename.
No subfolder, scenario JSON, HTML, dated snapshot or latest pointer is created.

## Workflow and dependencies

Read the preferred consolidated `captable_build` JSON through shared selection.
This is read-only selection, not a freshness guarantee: run `captable_build`
first to refresh source data. Direct analysis does not implicitly build or sync.
Bulk registry key `captable` declares `captable-build` as its prerequisite.

Calculate loan balances, ownership, conversion scenarios and rubric findings in
code. Each loan's cap/floor respects its stated share basis. Missing FX rates
prevent combined scenarios; defaults and unknown denominators remain disclosed
assumptions. Source dates are evidence metadata; interest accrues to the current
analysis date. There is no snapshot-selection `--as-of` parameter.

The final Markdown renders numeric tables deterministically and adds the model's
explanatory narrative. The prompt lives in `config/captable/narrative_prompt.md`.

## Side effects and failure behavior

A manual report wins before input reads. Generated reuse uses indexed startup
revision plus selected consolidated content, computed scenarios, analysis date,
configuration and tool version. Only the final Markdown and shared freshness
metadata are written. Missing or incomplete consolidated data raises with an
instruction to build first. Legacy snapshot, HTML and analysis files remain
untouched and are not automatically selected.

## Usage

```bash
conda run -n sictic-env python -m skills.harness /captable example
conda run -n sictic-env python -m skills.captable run --startup example
conda run -n sictic-env python -m skills.harness -- /captable example --pre-money 8000000 --investment 2000000 --currency CHF --fx-rate USD=0.88
```

`--dataset`/`-d` remain aliases. `/captable_analysis` and
`python -m skills.captable_analysis run` temporarily forward to this same workflow.
There is no separate old bulk-registry entry and no `render` command.

## References

- [Implementation](captable.py)
- [Build skill](../captable_build/SKILL.md)
- [Markdown renderer](../../lib/captable/render_markdown.py)
- [Domain limitations](../../docs/captable.md)
