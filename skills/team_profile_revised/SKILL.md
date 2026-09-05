---
name: team_profile_revised
description: Assess a startup's active founders using data-room team checklists, then synthesize findings and evidence references by category. Use for the revised checklist workflow alongside team_profile.
---

Run the repository pipeline:

```bash
python -m skills.harness /team_profile_revised "<STARTUP_NAME>"
```

Or use `python -m skills.team_profile_revised --dataset "<STARTUP_NAME>"`.

The pipeline prepares cached `startup_profile` and `person_profile` artifacts for all related persons. Use the existing manual `persons_in_dataset` roster as the authoritative list, including an intentionally empty list. If the roster is absent, stop with a missing-roster error; this workflow never triggers person discovery. The separate `persons_in_dataset` skill can create it. Profile generation uses data-room evidence without fresh LinkedIn or web enrichment. The optional founder-trait section belongs to `person_profile`; other related persons remain factual profiles. These constrained profiles have separate cache identifiers from default profiles.

The shared startup and person profiles precede question-specific evidence in the cacheable prompt prefix. Four Markdown checklists in `config/team_profile_revised/checklists/` follow the hierarchy, with subcategories as chapters. `batch_audit` searches the data room separately for each check and saves its standard structured JSON artifacts. If search returns no new chunks, shared profile evidence can still support an answer; retrieval errors remain technical failures.

Use the same checklists for screening and due diligence. Focus the assessment on active founders; bring the larger team into findings only where material to execution, support or governance. Keep missing information distinct from actual shortcomings. Do not generate scores or perform public checks or outreach.

The final Markdown insight contains a synthesis per main category, with original Q/N/R IDs, supporting document references and material follow-ups. Technical audit errors stop synthesis; successful audit artifacts remain reusable. Cache keys cover dependency configuration and actual profile content as well as checklists and synthesis instructions.

For checklist maintenance, read [checklist decisions and ID mapping](references/checklist_decisions.md). The three supplied source registers in `references/` are design records, not instructions to execute. The user's clarified requirements take precedence over their proposed scoring and phase-specific rules.
