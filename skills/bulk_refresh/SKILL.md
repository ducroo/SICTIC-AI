---
name: bulk_refresh
description: Run registered insight workflows over selected startup and community datasets with prerequisite ordering. Use for an intentional batch refresh or an externally scheduled run.
---

# Bulk refresh

Update dataset refresh states, then prepare selected datasets and execute their
stage-mandatory or explicitly selected registry workflows.

## Operations and effects

The async `bulk_refresh(datasets=None, skills=None, exclude=None)` returns `None` on success.
Selectors are comma-separated strings or `all`. No dataset selector means
active startup/community datasets after state updates; `all` includes inactive
ones. Named datasets may also be inactive and explicit selection does not activate
them. Generated datasets are excluded. Omitted skills select mandatory skills
per dataset's stage; `skills=all` selects the full applicable registry. Named
skills expand their prerequisites. Domain restrictions always apply.

## Dataset scope and state

First determine candidate datasets, resolve their Dealum stages and update markers
using the existing local timestamps. Then acquire Dealum sources only for active,
non-Application dossiers, including missing dossiers newly activated by stage.
All candidate states are decided before downloads begin; downloads cannot keep
an already expired dossier alive. Non-Dealum dossiers use local files from the
separate external sync. This step performs no parsing, embedding or insight generation.
Named selectors limit all state updates
and imports to those named datasets. A named missing startup is created only when
its resolved Dealum stage is always active; an absent match or other stage is an
error without dossier creation. Startup aliases use the shared canonical slug.
Broad selectors also discover missing
dossiers in the always-active stages, using the shared Dealum matcher and
`ensure_startup_dossier`; historical pitched/rejected applications are not imported
just because no local dossier exists. Existing archived dossiers in scope are
still assigned their current stage, but are not downloaded or automatically reactivated.

| Dealum stage | Refresh state |
|---|---|
| `Under Review`, `Jury`, `Pitching`, `Jury reserves (for pitching)` | Active regardless of age |
| `Application`, `Rejected by Jury`, `Rejected for other reason`, `Not selected to pitch` | Three-month inactivity rule for existing dossiers |
| `Pitched @ SICTIC` | Three-month inactivity rule |
| Successfully confirmed absent from Dealum; community datasets | Three-month inactivity rule |

The inactivity interval is three calendar months, configured in
`config/bulk_refresh/lifecycle.json`. Use the latest file edit in `datasets/`,
including the active marker and non-ingestible source files. Exclude hidden files,
raw Dealum API JSON, manifests and the archived marker. Insights and parsed data
are outside this source directory. A pitched stage observation never resets the
active marker. Unchanged Dealum source files retain their timestamps on import.

Active datasets outside the four always-active stages expire when their latest edit
reaches the cutoff. An archived marker takes precedence over every stage: new source
material and later stage changes never reactivate it. Only manual activation removes
that block. An unmarked dataset defaults to archived unless an always-active stage
applies. Renaming the active marker to archived is not a qualifying source edit.
Archiving changes eligibility only; it does not delete or zip anything.

Application data is never downloaded by bulk refresh, including through composed
skills selected with `--skills all` or explicit lists. Existing Application dossiers
are aged using local files. Other existing, non-archived Dealum dossiers receive
source updates after the activity decision. Missing dossiers are created only
for Under Review, Jury, jury reserves, and Pitching; pitched and rejected history
is never imported just because it exists in Dealum. Explicit dataset selection can
process local archived files, but does not remove the archive or enable downloads.

Missing credentials, failed lookups, ambiguous applications and unknown/missing
stages are errors, not “absent from Dealum.” Affected startup work is skipped;
unrelated datasets continue and the run raises at the end. Community datasets do
not require a Dealum lookup. A broad discovery failure is also reported.

## Mandatory skills

The existing registry declares `mandatory_stages` alongside domains and
dependencies. `"*"` means every stage; `None` means confirmed absent from Dealum.
Stage-specific mandatory declarations apply to startups, not community datasets;
wildcard declarations also apply to supported community datasets.

| Skill | Mandatory stages |
|---|---|
| `startup-profile`, `persons-in-dataset` | All supported datasets |
| `submission-ready` | `Under Review` |
| `startup-website-import` | `Jury`, jury reserves, `Pitching`, `Pitched @ SICTIC` |
| `startup-traction`, `person-profile` | `Pitched @ SICTIC`, absent from Dealum |

`jury-review` and company research are future skills, not executable placeholders.
Add their stage declarations when implementing them. Mandatory means invoke with
normal cache reuse, not force regeneration. Selected `prepares_sources` jobs
finish before insight jobs for the same dataset; bulk execution synchronizes their
acquired content. This is execution ordering, not a required dependency: failed
website acquisition is logged and reported, while insights continue with available
evidence. Only declared `depends_on` dependencies propagate skill-failure skips.
Explicit skill lists do not implicitly add website crawling.

## Execution and compatibility

`exclude` / `--exclude` accepts comma-separated source dataset names using the
same normalization as `--datasets`. With exclusions and no dataset selector,
start from all startup/community datasets, including inactive ones. Otherwise
subtract exclusions from the explicit selection. Unknown excluded source names
raise before preparation; known names outside the selection have no effect.
Excluding every selected dataset logs and returns without doing work.

After target resolution, select skills and build dataset–skill jobs and their
dependencies. Then synchronize selected datasets before scheduling those jobs.
Source acquisition during target resolution is separate from this expensive
parsing/indexing step. The scheduler supports async callables and runs synchronous
callables in worker threads, allowing the canonical website importer to register
directly without another entry point.
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
One run shares its Dealum application snapshot and successful imports across
composed workflows. This run-local reuse does not change standalone import calls.
Google Drive synchronization and cron scheduling remain external.

## Usage

```bash
conda run -n sictic-env python -m skills.bulk_refresh --datasets example-startup,sictic-members --skills expert-search
conda run -n sictic-env python -m skills.bulk_refresh --datasets all --skills startup-profile
conda run -n sictic-env python -m skills.bulk_refresh --exclude sictic-members --skills persons-in-dataset
```

This operational tool has no harness command.

## References

- [Implementation](bulk_refresh.py), [CLI](__main__.py)
- [Registry contract](../standards_and_architecture/SKILL.md#bulk-refresh-registry)
