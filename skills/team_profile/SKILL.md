---
name: team_profile
description: Synthesize a startup team assessment from standard person profiles and collective resume/CV evidence. Use for the original team workflow; team_profile_revised provides the checklist-based assessment.
---

# Team profile

Assess leadership and team composition from individual profiles and dataset evidence.

## Inputs and outputs

The async `team_profile(startup_name)` returns a one-element `list[InsightFile]`
containing the saved or reusable team assessment.

## Workflow and dependencies

Prepare the startup through `ensure_startup_dataset`, synchronize it and check
for a reusable team report. On a cache miss, call
`person_profile_as_person_objects(startup_name, names=None)` for the existing
roster. This uses the [standard person-profile workflow](../person_profile/SKILL.md)
and never discovers people. A missing roster must be created separately.

Retrieve collective resume/CV chunks, deduplicate them and individual mentions
by `chunk_id`, then synthesize the combined evidence and profile summaries.
The registry declares `startup-profile` and `person-profile` prerequisites;
the direct workflow calls person profiling only after its team-cache check.

## Side effects and failure behavior

Startup preparation may import configured Dealum data; synchronization updates
derived dataset content. Person profiling may enrich LinkedIn and save profiles.
An empty roster permits assessment from the remaining dataset evidence.

Profile failures propagate. Collective resume-search failures are logged and
assessment continues with available context. Generation failures raise.
The team cache tracks its own prompts and source revisions, but does not hash
supplied person-profile content; editing a profile alone need not refresh it.

## Usage

```bash
conda run -n sictic-env python -m skills.harness /team_profile "<STARTUP>"
```

The direct CLI uses `--startup`.

## References

- [Implementation](team_profile.py) and [prompts/queries](../../config/team_profile/)
- [Bulk registry](../skill_registry.py)
- [Checklist workflow](../team_profile_revised/SKILL.md)
