---
name: advocates
description: Rank SICTIC members to represent the organization at an event using its description and stored investor profiles. Use for panels, pitch events and presentations.
---

# Advocates

Find members whose experience fits an event's representation needs.

## Inputs and outputs

The async `advocates(event_name, event_description, target_members=None,
exclude_members=None, top_k=16)` returns one Markdown ranking in
`list[InsightFile]`. Optional person filters accept names, emails or LinkedIn
IDs using the [shared ranking selection rules](../ranking/SKILL.md).

Save through `InsightFile` under the `sictic-members` insights directory at
`advocates/<event-slug>-<model>.md`.

## Workflow and dependencies

Insert the event description into the configured advocates objective and rank
stored `investor_profile` insights from `sictic-members`. The objective covers
event fit, ecosystem involvement, speaking and leadership experience.
An existing member roster and eligible investor profiles are prerequisites.

Recompute on every invocation; this workflow does not select a cached or manual
output. Its configuration key records the objective, shared ranking and
structured-output configuration, event description and runtime filters/limit.
It is available through the harness, but not bulk refresh: an event name and
description are required.

## Side effects and failure behavior

Read existing people and profiles, call the shared ranking engine, and save
the completed report. There is no discovery, profile generation, ingestion or
outreach. Input and generation failures propagate without saving a new ranking.
Repeated invocations can replace the same event/model report.

## Usage

```bash
conda run -n sictic-env python -m skills.harness '/advocates "<EVENT_NAME>" --description "<EVENT_DESCRIPTION>"'
```

The direct CLI uses `--event` and `--description`, with optional comma-separated
`--include`/`--exclude` and `--top-k` (default 16). The harness exposes only the
event and description.

## References

- [Implementation](advocates.py)
- [Objective](../../config/advocates/objective.md)
- [Shared ranking contracts](../ranking/SKILL.md)
