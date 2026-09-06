---
name: linkedin_maintenance
description: Identify outstanding LinkedIn profiles, import manually retrieved JSON and diagnose registry/cache state. Use for the manual profile-retrieval workflow.
---

# LinkedIn maintenance

Reconcile manual LinkedIn retrieval with dataset caches and the shared registry.

## Operations and effects

- `missing`: read rosters from active startup/community datasets and call the
  resolver with `allow_scrape=False`. It can register missing profiles or
  reconcile cached state; it is not read-only. Print distinct URLs for open/failed
  registry entries. Missing or malformed rosters can abort the scan.
- `import`: read one JSON object or an array. Write cleaned profile JSON through
  `LinkedInProfileStore` to registered datasets and an optional explicit dataset,
  then remove resolved registry identities. Provider error/not-found records
  update registry status. Invalid/unidentified entries or entries without a
  target are skipped; writes already completed can remain after a later error.
- `diagnose`: report registry entries and missing/cached datasets without fetching
  profiles or writing changes.

`lib.people.linkedin.maintenance` owns import and diagnostic behavior. These
operations do not generate person profiles or edit the manual roster. There is
no harness command or bulk-refresh registration.

## Usage

```bash
conda run -n sictic-env python -m skills.linkedin_maintenance missing
conda run -n sictic-env python -m skills.linkedin_maintenance import profiles.json --dataset sictic-members
conda run -n sictic-env python -m skills.linkedin_maintenance diagnose
```

## References

- [Workflow adapter](maintenance.py), [CLI](__main__.py)
- [Shared import and diagnostics](../../lib/people/linkedin/maintenance.py)
- [LinkedIn persistence contracts](../standards_and_architecture/SKILL.md#linkedin-retrieval-and-persistence)
