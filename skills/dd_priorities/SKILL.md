---
name: dd_priorities
description: Merge the most important findings of a saved DD checklist report into up to five decision-relevant priorities, including risks that grow when findings occur together. Use after dd_checks when the most material concerns and follow-up actions are needed.
---

# DD priorities

Prioritize the most important concerns and evidence gaps in an existing DD report.

## Inputs and outputs

The async `dd_priorities(startup)` returns one `InsightFile` in a list,
named `dd-priorities-<startup>-<model>.md`.

## Workflow and dependencies

Resolve the canonical startup slug and read the preferred stored `dd_checks`
report with `find(selection="any")`. Input selection does not establish freshness.
The registry declares `dd-checks`; direct calls never rerun it.

Take the report's most important findings through
`dd_checks.most_important_findings`. These are the checks with the highest
importance, sorted by it. A report without that section, such as a manual one,
is used completely.

Read the report before checking manual-first output reuse. The cache covers
indexed startup revisions, effective synthesis instructions and the selected
findings. On a miss, send the findings to `generate_markdown`.

The prompt asks for up to five distinct priorities: merge findings about the
same issue, name combinations that make a risk larger, and order the result by
importance for the investment decision. Each priority keeps supporting check
IDs, citations and follow-ups. These semantic requirements are not
mechanically verified.

## Side effects and failure behavior

Read stored inputs, call a model when needed and save the synthesis. No discovery,
source import, semantic search or ranking engine is involved. Missing or empty
DD reports raise with instructions to run DD checks; generation failures propagate.

## Usage

```bash
conda run -n sictic-env python -m skills.harness '/dd_priorities "<STARTUP>"'
```

The direct CLI uses `--startup`.

## References

- [Implementation](dd_priorities.py)
- [Synthesis instructions](../../config/dd_priorities/llm_instructions.md)
- [Source workflow](../dd_checks/SKILL.md)
