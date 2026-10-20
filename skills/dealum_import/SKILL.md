---
name: dealum_import
description: Import all Dealum applications and attachments for a startup, or one application by code.
---

# Dealum import

Import application source snapshots through the shared Dealum library.

## Operations and effects

The async `dealum_import(startup)` returns `DealumImportResult`, not
`list[InsightFile]`. Shared matching accepts exact normalized names or application
codes, then falls back to explicitly configured startup aliases. Name/alias imports
retain all matching applications. An explicit application code imports only that
application. The result's identity, contact source paths and stage describe the latest
matched application; `changed` and file counts cover the whole import, and
`applications_imported` reports its application count. Stage reconciliation retains
the existing latest-application selection policy.

The shared importer requires configured Dealum credentials. It creates the
startup dossier and normally activates it. It stages application Markdown,
raw JSON, metadata and downloaded attachments before replacing the
`datasets/dealum/YYYY-MM-DD/` snapshot, using the UTC date of `createDate`.
Each application has its own manifest, raw JSON, application text and `documents/`.
Removed attachments disappear only from that application's replacement; previously
stored applications remain even if absent from a later API response.
A download failure preserves that application's prior snapshot. Applications already
updated remain saved, but the collection is not marked successfully refreshed.
The importer does not perform
dataset indexing or generate insight reports.
Generated application Markdown and downloaded `.md` attachments are stored as
`.md.txt` (content unchanged) to avoid Markdown-to-Google-Docs conversion during
Drive sync. Other extensions are unchanged. The next successful snapshot replaces
legacy local `.md` paths; existing Google Docs require separate sync reconciliation.
Identical source snapshots are not replaced; only changed bookkeeping is updated.
For partial source changes, unchanged files are reused through staged hard links,
preserving their content, identity and modification timestamps. Within a bulk-refresh
run, successful imports and the application list
are reused by composed workflows; standalone imports retain their normal behavior.
Per-application caching allows a subsequent startup-wide import after a code-only
import without repeating the successful application's downloads. Code-only imports
do not mark the whole startup collection fresh. The root `manifest.json` points to
the latest stored application and records successful full-refresh time; shared
manifest readers preserve existing latest-application URL and freshness behavior.

On the next import, legacy flat snapshots are atomically moved into their dated
folder using saved raw `createDate`, preserving content and timestamps. Normal dataset
synchronization reconciles the moved source paths. Missing/invalid creation dates,
same-day applications with different IDs, changed dates for an existing ID, or
unidentifiable existing folders are reported without overwriting them. No fallback
date or automatic suffix is invented. A per-dossier lock serializes imports/migration.
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
