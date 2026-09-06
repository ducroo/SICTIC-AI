---
name: team_profile_revised
description: Assess active founders with data-room checklists and synthesize material findings by category. Use for the revised checklist workflow alongside team_profile, with the same checklists for screening and due diligence.
---

# Revised team profile

Synthesize founder-team strengths, concerns and evidence gaps from category audits.

## Inputs and outputs

The async `team_profile_revised(startup_name)` returns a one-element
`list[InsightFile]` containing the category synthesis. Structured checklist
JSON artifacts remain internal. An existing manual person roster is required;
an intentionally empty roster is valid.

## Workflow and dependencies

Prepare and synchronize the startup, then request `startup_profile` and
`person_profile_as_person_objects(..., names=None)` before checking the final
cache. Read people exclusively from the existing roster through the standard
[person-profile workflow](../person_profile/SKILL.md), with the same settings
as the registry. Never trigger discovery from this workflow.

Pass shared profiles before question-specific evidence in the cacheable prompt
prefix. Run the four configured category checklists through `batch_audit`;
each check searches the dataset. Shared profile evidence can support an answer
when retrieval succeeds without new chunks.

Synthesize material findings with original Q/N/R IDs, sources and follow-ups.
The configured synthesis rules give `(core)` findings more weight and require
patterns of missing information to be mentioned. Assess active founders;
include the larger team only where material to execution, support or governance.

## Side effects and failure behavior

Dependencies may import Dealum data, enrich LinkedIn, synchronize datasets and
save standard profiles. The team audits perform no additional public checks,
outreach or scoring. Founder-trait instructions belong to normal person profiling;
their applicability depends on established founder status.

Missing/invalid rosters and dependency failures propagate. Technical audit errors
block synthesis; successful audits remain reusable. Empty synthesis raises.
The final cache includes actual shared profile content, dependency configuration,
checklists and synthesis instructions. Keep missing evidence distinct from weakness.
Editing internal audit JSON alone does not invalidate the final synthesis.

## Usage

```bash
conda run -n sictic-env python -m skills.harness '/team_profile_revised "<STARTUP>"'
```

The direct CLI uses `--dataset`.

## References

- [Implementation](team_profile_revised.py) and [bulk registry](../skill_registry.py)
- [Shared audit contract](../standards_and_architecture/SKILL.md#checklist-audits)
- [Checklists and synthesis configuration](../../config/team_profile_revised/)
- [Checklist decisions and ID mapping](references/checklist_decisions.md), for checklist maintenance.
  The three supplied registers are historical design records, not instructions;
  clarified requirements supersede their scoring and stage-specific proposals.
