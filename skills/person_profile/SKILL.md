---
name: person_profile
description: Generate individual profiles from an existing person roster, LinkedIn enrichment and dataset evidence, including founder-trait assessment for active founders. Use for selected people or the complete roster.
---

# Person profile

Generate standard individual profiles for use directly or by other skills.

## Inputs and outputs

The async API accepts `dataset_name`, optional `names` (a string or list),
and keyword-only `include_dataset_context=True`. Omitted names select everyone
in the roster. `person_profile` returns `list[InsightFile]`; the
`person_profile_as_person_objects` adapter runs the same workflow and returns
populated `list[Person]`.

Explicit unmatched names currently create sparse `Person` inputs for profiling;
they do not change the roster. The roster remains required even for these calls.

## Workflow and dependencies

Read the existing roster, resolve LinkedIn profiles and synchronize the dataset
before selecting reusable individual profiles. On a cache miss, combine the
resolved LinkedIn payload with `build_person_dossier` evidence when
`include_dataset_context` is enabled, then synthesize the profile.

Biographical and founder-trait instructions always belong to the standard prompt.
Apply the trait assessment only to explicitly identified active founders; keep
other people factual. [Shared profile standards](../standards_and_architecture/SKILL.md#standard-person-profiles)
own identifiers, filenames, manual precedence and compatibility between consumers.

Direct calls never discover people. Run [persons_in_dataset](../persons_in_dataset/SKILL.md)
first when the roster is missing; bulk refresh declares that dependency.

## Side effects and failure behavior

LinkedIn resolution can fetch profiles and update stored JSON and registry state.
Resolution and synchronization occur even before a manual or reusable profile
is selected. Generation settings affect freshness metadata, not filenames.

A missing or invalid roster raises. An empty roster with no explicit names
returns `[]`. With no dossier, mentions or LinkedIn payload, generation saves a
profile with a no-information note. Individual generation failures are collected:
successful files remain, but the API raises instead of returning a partial list.

## Usage

The harness requires a person; the direct CLI also supports the complete roster.

```bash
conda run -n sictic-env python -m skills.harness /person_profile "<DATASET>" "<NAME>"
conda run -n sictic-env python -m skills.person_profile --dataset "<DATASET>"
conda run -n sictic-env python -m skills.person_profile --dataset "<DATASET>" --person "<NAME_1>, <NAME_2>"
```

## References

- [Implementation and adapter](person_profile.py)
- [Profile prompts and query](../../config/person_profile/)
- [LinkedIn resolution contract](../standards_and_architecture/SKILL.md#linkedin-retrieval-and-persistence)
