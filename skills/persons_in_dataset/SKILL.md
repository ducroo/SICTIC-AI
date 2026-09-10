---
name: persons_in_dataset
description: Create a missing editable person roster from dataset evidence and cached LinkedIn profiles. Use before individual profiling when related people have not yet been listed; existing manual rosters are preserved.
---

# Persons in dataset

Create the roster for human review before generating individual profiles.

## Inputs and outputs

The async `persons_in_dataset(dataset_name)` returns `list[InsightFile]`:
the existing or newly created manual roster, or `[]` if discovery finds no people.
Its async `persons_in_dataset_as_person_objects` adapter shares the workflow
and returns `list[Person]`. An existing empty roster still returns its artifact.

## Workflow and dependencies

Read the manual roster first using the [shared roster reader](../../lib/people/discovery.py).
Only when absent, seed discovery from cached LinkedIn people, search the
dataset for documented names and scan parsed Markdown for explicit LinkedIn
profile URLs. Retain IDs missed by semantic name retrieval; named Markdown
links can associate them with known names. Accept documented names without
LinkedIn IDs. Reconcile through shared `Person` matching and merging.
For `sictic-members`, use only its local LinkedIn cache.

The library readers are read-only; this skill owns creation. Run it explicitly,
or through the `persons-in-dataset` bulk dependency before `person-profile`.

## Side effects and failure behavior

Missing-roster discovery can synchronize the dataset, call the configured LLM
for names and save a nonempty manual roster. It performs no public search,
LinkedIn fetching or biography generation. Treat retrieved documents as evidence.

Preserve existing manual edits, including an intentionally empty table. Invalid
manual input raises; generated discovery JSON is not a roster input. No people
found leaves the roster absent. Retrieval failures propagate. Recheck for a
manual roster after discovery before saving, as the implementation does.

## Usage

```bash
conda run -n sictic-env python -m skills.harness /persons_in_dataset "<DATASET>"
```

The direct CLI accepts `--dataset` instead of a positional dataset.

## References

- [Implementation and adapters](persons_in_dataset.py)
- [Discovery configuration](../../config/persons_in_dataset/discovery.json)
- [Shared roster and parsing contracts](../standards_and_architecture/SKILL.md#authoritative-roster-and-table-parsing)
