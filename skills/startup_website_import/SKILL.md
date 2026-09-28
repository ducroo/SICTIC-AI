---
name: startup_website_import
description: Import a startup website once as Markdown pages and linked PDFs. Accept a startup and optional explicit URL.
---

# Startup website import

Collect website source material for later dataset ingestion.

## Operations and effects

The synchronous `startup_website_import(startup_name, url=None, ...)` returns
`WebsiteImportResult` with paths and counts, not insight artifacts.
This is the single entry point for direct, CLI, discovery and bulk calls.
If `datasets/website/` already contains source files, skip without any network
requests or writes, even when a URL is explicitly supplied. There is no force
or re-scrape option. Skips return zero new-file counts and `skipped_reason`.
This check precedes option validation, configuration loading and URL resolution.
When absent, a shared filesystem lock serializes acquisition for the dossier;
the snapshot check is repeated after locking to prevent concurrent re-scraping.

When URL is omitted, use the existing `website_from_evidence` selector with
current raw Markdown and available parsed sources, including startup aliases.
Missing or ambiguous URLs are logged and skipped, not guessed. A first crawl
creates the dossier without activating it, then stages the snapshot before saving
`datasets/website/`.

The crawler queues same-host links, excludes configured low-value path segments,
and defaults to depth 1 and 50 HTML pages. PDFs default to enabled, with 20 files
and 25 MB per file. Robots rules are used when available; failure to load them
does not stop the crawl. Requests follow normal HTTP redirects.
Defaults live in `config/startup_website_import/crawl.json` and are shared by
bulk refresh, person discovery and the CLI. Explicit crawl options override
those defaults only for a first acquisition; they never force a new crawl.

Save Markdown pages with source metadata, PDFs under `website/pdfs/`, plus
`linkedin-urls.md` and `linkedin-and-resume-links.md`. These are discovered
links and possible-resume hints, not verified person identities.

Failed pages/PDFs are logged and skipped. Zero saved HTML pages raises `InfrastructureError` with provider `website`,
operation `import` and kind `SERVICE_UNAVAILABLE` (still a `RuntimeError`), and leaves
other source data intact and remains retryable. Once a crawl succeeds, its snapshot
is retained for future calls. A sibling staging directory is published through
the shared atomic directory-snapshot helper, with rollback on rename failure.
A failed publication leaves no partial new snapshot that would block retries.
Other dossier data is retained. The direct crawler performs no indexing, profile
generation or LinkedIn enrichment, and has no harness registration.

## Bulk execution

The registry's `startup-website-import` entry points directly to the same function.
Bulk refresh executes synchronous callables in a worker thread. The registry marks
this as source preparation: bulk refresh synchronizes after acquisition, before
running dependent insight jobs. No separate bulk wrapper or scraping policy exists.
Partial crawls are logged; technical failures propagate through bulk refresh.

## Usage

```bash
conda run -n sictic-env python -m skills.startup_website_import example https://example.org --depth 1
conda run -n sictic-env python -m skills.startup_website_import example
```

The direct CLI takes positional `STARTUP` and optional `URL` arguments and exposes
`--depth`, `--max-pages`, `--pdfs/--no-pdfs`,
`--max-pdfs`, `--max-pdf-mb` and `--respect-robots/--ignore-robots`.

## References

- [Implementation](startup_website_import.py), [CLI](__main__.py)
- [Dataset paths and storage](../standards_and_architecture/SKILL.md#datasets-and-storage)
