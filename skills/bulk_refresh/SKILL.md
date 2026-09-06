---
name: bulk_refresh
description: Run registered insight workflows over selected startup and community datasets with prerequisite ordering. Use for an intentional batch refresh or an externally scheduled run.
---

# Bulk refresh

Prepare selected datasets and execute their applicable registry workflows.

## Operations and effects

The async `bulk_refresh(datasets=None, skills=None)` returns `None` on success.
Selectors are comma-separated strings or `all`. No dataset selector means
active startup/community datasets; `all` includes inactive ones. Named datasets
may also be inactive. Generated datasets are excluded. Omitted skills select
the full registry; named skills expand their prerequisites.

Prepare and synchronize every selected dataset before running skills.
Independent ready jobs run concurrently. Cross-domain dependencies cover
prerequisite nodes within the selected dataset scope; they do not add datasets.
The [registry](../skill_registry.py) owns supported domains and dependencies.

Pre-ingestion failures skip affected jobs and their dependants. Skill failures
also propagate skips, while independent work continues. Completed artifacts
remain saved. After runnable work finishes, problems raise `BulkRefreshError`;
an empty dataset selection logs and returns.

Side effects are those of preparation and selected skills, including source
imports, discovery, enrichment, conversion, indexing and report generation.
Each skill owns artifact reuse. The command does not itself install a schedule.

## Usage

```bash
conda run -n sictic-env python -m skills.bulk_refresh --datasets example-startup,sictic-members --skills expert-search
conda run -n sictic-env python -m skills.bulk_refresh --datasets all --skills startup-profile
```

This operational tool has no harness command.

## References

- [Implementation](bulk_refresh.py), [CLI](__main__.py)
- [Registry contract](../standards_and_architecture/SKILL.md#bulk-refresh-registry)
