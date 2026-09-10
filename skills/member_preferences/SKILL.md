---
name: member_preferences
description: Read the existing member roster and attach communication preferences to canonical Person objects. Use when a consumer needs member opt-outs; the current source is a default-assignment stub.
---

# Member preferences

Supply roster identities with namespaced, skill-specific preferences.

## Inputs and outputs

The synchronous `member_preferences(dataset_name="sictic-members")` returns
`list[Person]`. `preferences_for(person)` reads the preference dictionary
without creating it; `render_member_preferences(people)` renders a Markdown table.

## Workflow and dependencies

Read the existing roster through `lib.people.discovery.persons_in_dataset`.
Under `person.adhoc_data["member_preferences"]`, default an absent
`deep_dive_invitation` value to `standard`; preserve any existing value.

The current implementation does not read a Google Sheet. The documented
invitation values are `none`, `fewer`, `standard` and `more`; consumers decide
their effect. There is no bulk-refresh registration.

## Side effects and failure behavior

Only returned in-memory Person objects are augmented. No discovery, enrichment,
external request or file write occurs. An empty valid roster returns an empty
list; missing or malformed rosters raise through the shared reader.

## Usage

```bash
conda run -n sictic-env python -m skills.harness /member_preferences
```

Both harness and direct CLI accept `--dataset`.

## References

- [Implementation](member_preferences.py)
- [Person and roster contracts](../standards_and_architecture/SKILL.md#people-identity-evidence-and-workflows)
