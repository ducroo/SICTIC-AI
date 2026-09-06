---
name: startup_traction
description: Summarize commercial traction and agreements from a startup's data room. Use for LoIs, MoUs, pilots, partnerships and traction evidence.
---

# Startup traction

Summarize retrieved commercial evidence in a table and synthesis.

## Inputs and outputs

The async `startup_traction(startup_name)` returns a one-element
`list[InsightFile]`, named `startup-traction-<startup>-<model>.md`.
The configured query and instructions define the requested categories.

## Workflow and dependencies

Prepare and synchronize the startup, then select a manual override or reusable
report. Freshness uses indexed startup revisions and the configured query and
instructions.

Call `dataset_chat(dataset_name=..., queries=..., prompt=...)` with
`max_chunks=100` and `strict_insufficient_context=False`. Retrieval is bounded;
this does not establish exhaustive coverage of every agreement.

The registry declares `startup-profile`, but direct traction generation neither
calls nor reads that profile.

## Side effects and failure behavior

Preparation may import Dealum data; synchronization/retrieval may convert and
index documents. Generation saves the traction report and performs no outreach.

Technical errors propagate. Contrary to the former documentation, missing
context does not necessarily raise: a nonempty dataset-chat fallback is saved;
a falsey response is replaced with “No relevant information found.”
Whether missing evidence should block output remains a separate behavior decision.

## Usage

```bash
conda run -n sictic-env python -m skills.harness '/startup_traction "<STARTUP>"'
```

The direct CLI uses `--startup`.

## References

- [Implementation](startup_traction.py)
- [Configuration](../../config/startup_traction/)
- [Dataset chat](../dataset_chat/SKILL.md)
