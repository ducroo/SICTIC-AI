---
name: investor_profile
description: Compose investor profiles from stored person profiles and manual investment track records. Use for roster members with LinkedIn IDs; composition does not discover people or regenerate source profiles.
---

# Investor profile

Append the matching manual track record and preferences to stored person profiles.

## Inputs and outputs

The async `investor_profile` accepts `source_dataset="sictic-members"` and
optional `names: list[str]`, returning `list[InsightFile]`. Only selected roster
members with LinkedIn IDs and matching stored profile files are eligible.
Preserve each source model variant in the output.

## Workflow and dependencies

Read the roster and files under its `person-profile` insight directory. Read
track records from `datasets/track-record/<linkedin-id>.md` in the same dataset;
save the combined result under `insights/investor-profile/<linkedin-id>-<model>.md`.
Use configured dataset locations for these paths.

Direct composition requires the existing roster and person-profile directory.
It does not refresh these inputs. Bulk refresh declares `person-profile` as
its prerequisite. `read_investor_profiles(source_dataset, names)` is a separate
read-only selector returning a name-to-content dictionary, without composition.

## Side effects and failure behavior

Composition calls no LLM and performs no ingestion, discovery or LinkedIn fetch.
It writes changed output content and retains identical files. Missing track
records produce a note; unmatched requested names and ineligible files are
skipped. A missing roster or source directory raises. Per-file failures leave
successful outputs saved, then raise instead of returning a partial list.

Known manual-output conflict: a manual person-profile source can cause composition
to overwrite the corresponding edited manual investor profile. This remains an
unresolved violation of [manual preservation](../standards_and_architecture/SKILL.md#naming-reading-and-saving),
not a supported exception to that rule.

## Usage

```bash
conda run -n sictic-env python -m skills.harness -- /investor_profile --source-dataset "<DATASET>"
```

The direct CLI also accepts `--person "<NAME_1>, <NAME_2>"`; omission selects all
eligible roster members. Both CLIs default to `sictic-members`.

## References

- [Composition and read-only selector](investor_profile.py)
- [Source profile workflow](../person_profile/SKILL.md)
- [Shared identity and matching](../standards_and_architecture/SKILL.md#identity-and-matching)
