---
name: dealum_import
description: Import an explicitly named Dealum application and its attachments into a startup dataset. Use an exact normalized name or application code.
---

# Dealum import

Import the application's source snapshot through the shared Dealum library.

## Operations and effects

The async `dealum_import(startup)` returns `DealumImportResult`, not
`list[InsightFile]`. Shared matching accepts exact normalized names or application
codes. Duplicate names select the latest available application date; unresolved
ties or missing usable dates require a more specific identifier.

The shared importer requires configured Dealum credentials. It creates the
startup dossier and normally activates it. It stages application Markdown,
raw JSON, metadata and downloaded attachments before replacing the
`datasets/dealum/` snapshot. Removed attachments disappear from the replacement.
A download failure preserves the prior snapshot. The importer does not perform
dataset indexing or generate insight reports.

Inspect the result's `application_found`, `changed`, counts and paths.
The direct CLI continues after individual failures and exits with code 1 if
any import fails or has no application. Python errors propagate; the harness
formats its single-startup result. No Dealum stage is changed.

## Usage

```bash
conda run -n sictic-env python -m skills.harness '/dealum_import "<EXACT_NAME_OR_CODE>"'
conda run -n sictic-env python -m skills.dealum_import "Avientus, daav"
```

Only the direct CLI splits a comma-separated startup list.
This skill is not registered for bulk refresh; other workflows may invoke the
shared, gated `ensure_startup_dataset` preparation separately.

## References

- [Skill adapter](dealum_import.py), [direct CLI](__main__.py)
- [Shared importer](../../lib/startups/dealum/importing.py)
- [Matching](../../lib/startups/dealum/matching.py)
- [Setup](../../docs/installation-and-operations.md)
