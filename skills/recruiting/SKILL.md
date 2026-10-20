---
name: recruiting
description: Assess applicants from resumes and LinkedIn against shared job criteria, producing individual audits and a comparison table.
---

# Recruiting

## Inputs and outputs

The async API `recruiting(dataset_name, criteria=None)` accepts an existing
dataset and optional job advert/criteria text. Prefer a community dataset for
recruitment, such as `2026-mediamatiker`, with resumes under its `datasets/`.
No new storage domain is introduced.

Return a flat `list[InsightFile]`: selected criteria, canonical JSON audits,
individual Markdown assessments and the overview. Person profiles are generated
and saved by the standard person-profile workflow.

## Workflow

1. Select manual job criteria first, otherwise reuse or distil supplied text.
   Without new text, select existing criteria; fail if absent.
   Save `job-criteria-<dataset>-<model>.md` under insights.
   Generated criteria use one H2 Criteria heading and 6–8 H3 criteria in
   importance order, with required/desirable distinctions in descriptions, no H1.
   Keywords are optional. Do not add an H1 when manually editing criteria.
2. Run `persons_in_dataset`, then `person_profile_as_person_objects`.
   Manual applicant rosters are authoritative. Non-startup datasets use generic
   discovery with no startup profile, company website or company-wide search.
3. Gather each person's dedicated dossier through `build_person_dossier`,
   resolved LinkedIn payload, applicant mentions (including application letters)
   and standard person profile. The shared gatherer scans current parsed sources using roster-unique name
   combinations and exact contacts; both its
   dossier documents and mentions are supplied to the audit. Preserve source/page
   references. Resume and LinkedIn experience outweigh motivational claims.
   Do not feed other applicants' evidence.
4. Prepend the canonical person identifier as the checklist H1. Run `batch_audit`
   with `skill_name="recruiting"`, supplied evidence and `retrieve=False`.
   There is one LLM call per criterion per applicant, excluding correction retries.
   The rubric is 1–6: 6 flags overqualification/potential role mismatch, not
   stronger fit than 5 or presumed unwillingness to accept. Missing evidence uses null/unconfirmed internally and
   appears as ? in overview score cells. The overview includes the score legend
   from the configured schema.
5. Validate the complete structured audit and render through the shared renderer.
   Audits retain the standard `batch-audit/recruiting-<identifier>-<model>.json`;
   reports use `recruiting/<identifier>-<model>.md`.
6. Make one structured LLM call with the criteria descriptions, populated Person
   objects (including profiles and source evidence), and all completed assessments
   to rank candidates and produce 2–3 sentence comparative rationales. Supply
   structured assessments once, adding separate Markdown reports only for manual
   overrides. Validate complete, unique ranks and present the overview in rank order,
   copying criterion scores unchanged: `recruiting-<dataset>-<model>.md`.
   Prioritise must-haves over desirable criteria; unknowns remain uncertainty.
   Ranking is advisory, with no calculated total score.

All paths use InsightFile; identity uses Person.identifier (LinkedIn ID, email,
then name). Prompts and schemas live under `config/recruiting`.
Criteria, evidence, schemas and prompts participate in relevant freshness keys.
Manual Markdown reports remain untouched; overview scores come from canonical
JSON audits, and linked manual reports are included when synthesising rationales.

## Errors and side effects

Discovery/profiling may ingest sources, resolve LinkedIn requests and call models.
Criteria extraction and final rationales use the shared generation/reviewer APIs.
No outreach occurs. No bulk-refresh registration is added.

Invalid criteria fail before discovery. Missing applicants raise. Technical audit
failures remain errors, not low scores; successful individual artifacts remain
saved, but the run raises without generating a new overview if any applicant fails.
Old overviews are not deleted. Profile-generation failures retain the standard
person-profile behaviour.

## Usage

```bash
conda run -n sictic-env python -m skills.recruiting --dataset "<DATASET>" --criteria "Job requirements"
conda run -n sictic-env python -m skills.recruiting --dataset "<DATASET>"
conda run -n sictic-env python -m skills.harness '/recruiting "<DATASET>" --criteria "Job requirements"'
```

The direct CLI and harness accept either `--criteria` text or `--criteria-file`
(a UTF-8 text/Markdown file), not both. Python callers pass text.

## References

- [Standards](../standards_and_architecture/SKILL.md)
- [Person discovery](../persons_in_dataset/SKILL.md)
- [Person profiles](../person_profile/SKILL.md)
