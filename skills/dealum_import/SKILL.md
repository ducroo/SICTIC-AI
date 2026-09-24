---
name: dealum_import
description: Import an explicitly named Dealum application and its attachments into a startup dataset. Use an exact normalized name or application code.
---

# Dealum import

Import the application's source snapshot through the shared Dealum library.

## Operations and effects

The async `dealum_import(startup)` returns `DealumImportResult`, not
`list[InsightFile]`. Shared matching accepts exact normalized names or application
codes, then falls back to explicitly configured startup aliases. Duplicate matches
select the latest available application date; unresolved
ties or missing usable dates require a more specific identifier.

The shared importer requires configured Dealum credentials. It creates the
startup dossier and normally activates it. It stages application Markdown,
raw JSON, metadata and downloaded attachments before replacing the
`datasets/dealum/` snapshot. Removed attachments disappear from the replacement.
A download failure preserves the prior snapshot. The importer does not perform
dataset indexing or generate insight reports.
Identical source snapshots are not replaced; only changed bookkeeping is updated.
For partial source changes, unchanged files are reused through staged hard links,
preserving their content, identity and modification timestamps. Within a bulk-refresh
run, successful imports and the application list
are reused by composed workflows; standalone imports retain their normal behavior.
Bulk refresh disables imports for Application-stage and already archived dossiers;
composed calls return `imported=False` without downloads or activation for those
dossiers. This restriction is scoped to the bulk run, not standalone explicit imports.

Inspect the result's `application_found`, `changed`, counts and paths.
The direct CLI continues after individual failures and exits with code 1 if
any import fails or has no application. Python errors propagate; the harness
formats its single-startup result. No Dealum stage is changed.

## Usage

```bash
conda run -n sictic-env python -m skills.harness '/dealum_import "<EXACT_NAME_OR_CODE>"'
conda run -n sictic-env python -m skills.dealum_import "Avientus, daav"
```

The direct CLI's positional `STARTUPS` argument accepts a comma-separated list.
The harness's positional `startup` accepts one name or code.
This skill is not registered for bulk refresh; other workflows may invoke the
shared, gated `ensure_startup_dataset` preparation separately.

## References

- [Skill adapter](dealum_import.py), [direct CLI](__main__.py)
- [Shared importer](../../lib/startups/dealum/importing.py)
- [Matching](../../lib/startups/dealum/matching.py)
- [Setup](../../docs/installation-and-operations.md)
