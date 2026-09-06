---
name: suggested_startups
description: Rank stored startup profiles for selected investors using their existing investor profiles. Use for personalized startup suggestions without discovery or profile generation.
---

# Suggested startups

Match startup profiles to each investor's professional background and interests.

## Inputs and outputs

The async `suggested_startups(dataset_name="sictic_members", startups=None,
investors=None, max_startups=16)` returns one Markdown table per investor in
`list[InsightFile]`. Tables contain Startup, Dealum and Rationale columns,
ordered by rank.

Pass `Person.identifier` to `InsightFile`. Eligible investors have LinkedIn IDs,
giving `suggested-startups/<linkedin-id>-<model>.md` within the community's
insights directory. Use display names only in report text. Investor-profile
inputs use the same LinkedIn identity.

## Workflow and dependencies

Read the existing canonical roster with the synchronous
`lib.people.discovery.persons_in_dataset` reader. Resolve supplied investor
names or LinkedIn IDs to roster members. Omitted or empty investor selection
uses all eligible members; LinkedIn IDs are required.

Resolve supplied startup names to dataset slugs and remove duplicates. Omitted
or empty startup selection lists startup datasets, excluding configured
community and ignored datasets. This default does not filter by active status.
Read preferred stored `startup_profile` and `investor_profile` insights;
manual input profiles take precedence. Validate all required profiles before
making any ranking calls.

Insert each investor profile into the configured objective, then call
`ranking_top_k` and `ranking_rationale` with canonical startup dataset IDs.
Use the shared engine's default batch size. The prompt asks for previously
seen startups to rank last; strict exclusion is not enforced, so they may
appear when the requested limit exceeds the eligible candidates.

Recompute on each invocation; no cached or manual suggestion output is selected.
The configuration key records the objective, shared ranking/structured-output
configuration, selected startup list and limit. Direct calls are read-only
for source profiles. Bulk refresh declares `startup-profile` and
`investor-profile` prerequisites; their execution follows registry scope.

## Side effects and failure behavior

Call models and save one report per investor through `InsightFile`.
No discovery, enrichment, source-profile refresh, ingestion or outreach occurs.
Dealum links use stored manifest metadata without external requests.

Unresolved requested investors, missing LinkedIn IDs in explicit selections,
an empty resolved request, or missing/duplicate startup profiles raise before
generation. Default investor selection skips people without LinkedIn IDs;
missing selected investor profiles raise.

Investors are processed concurrently. Generation or validation failures prevent
saving that investor's new report. Other investors continue and successful
reports remain saved; after processing all investors, any failure raises an
aggregate `RuntimeError` rather than returning a partial list. Save failures
are also included in that error.

## Usage

```bash
conda run -n sictic-env python -m skills.harness '/suggested_startups --startups "<startup1>,<startup2>" --investor "<name-or-id1>,<name-or-id2>"'
```

The harness uses comma-separated startup and investor lists. The direct CLI uses
repeated `--startups` options and a comma-separated `--investor` value.
Both accept `--max-startups` (default 16); only the Python API exposes
`dataset_name`.

## References

- [Orchestration](suggested_startups.py), [input selection](inputs.py)
- [Generation and rendering](generation.py)
- [Objective](../../config/suggested_startups/suggested_startups_prompt.md)
- [Shared ranking contracts](../ranking/SKILL.md)
