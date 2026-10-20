---
name: startup_website_import
description: Import a startup website once as Markdown pages and linked documents, identifying formats from downloaded content. Accept a startup and optional explicit URL.
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
and defaults to depth 1 and 50 HTML pages. Document downloads default to enabled,
with 20 documents and 25 MB per response. Robots rules are used when available; failure to load them
does not stop the crawl. Requests follow HTTP redirects, but destinations are
validated before any content or links are saved.
Defaults live in `config/startup_website_import/crawl.json` and are shared by
bulk refresh, person discovery and the CLI. Explicit crawl options override
those defaults only for a first acquisition; they never force a new crawl.

### Website relevance checks

`config/startup_website_import/content_policy.json` owns the deterministic rules:

- Amazon marketplace domains and short links are not company websites. The shared
  `website_from_evidence` selector ignores them; explicit inputs are logged and
  skipped before fetching. Book/product links in original source documents remain
  intact, but cannot initiate an Amazon storefront crawl.
- HTTP/HTTPS and `www` hostname changes are accepted. Other hostname changes are
  skipped unless explicitly verified in `approved_redirect_hosts`, a mapping from
  source hostname to a list of permitted destination hostnames (lowercase, without
  `www`). This applies to subpages and document downloads as well as the homepage.
  Alternatively, supply the verified new website URL explicitly. Company-name
  text on a destination page alone does not establish ownership. Rejected
  destinations are neither saved nor followed; an accepted homepage hostname
  change reloads robots rules for that host.
- HTML titles, main headings, visible text and link targets are screened for
  configured gambling-spam signatures. Gambling landing pages are rejected.
  Short isolated spam labels/links are removed before Markdown rendering, link
  discovery and crawl expansion. Pages dominated by spam, or with longer spam
  blocks that cannot safely be isolated, are skipped. Ordinary mentions of casinos
  or gambling in legal terms, business descriptions or articles are retained.

These checks use no LLM calls. They log rejection/cleanup reasons and preserve the
existing failed-page count and zero-HTML failure behavior. They do not prove company
identity or detect every form of spam. Existing snapshots are still reused first;
the importer does not automatically rewrite or re-index old source material.

Every fetched response is classified by the shared
`lib.infrastructure.document_formats.detect_document_extension` before saving.
Content takes precedence over URL suffixes and HTTP Content-Type. HTML becomes
Markdown through the existing page renderer; supported documents are saved with
their detected extension. Supported downloads are PDF, DOCX, XLS/XLSX/XLSM, PPTX,
RTF, TXT, Markdown, JSON and CSV. Office ZIP containers are inspected for their
document structure; generic archives, images, other unsupported formats and
unidentified binary content are logged and skipped. Format detection does not
guarantee that a document is uncorrupted; full validation remains with conversion.
Text uses UTF-8, BOM-marked UTF-16 or an explicitly declared HTTP/HTML charset;
saved text is normalized to UTF-8. Undecodable content is skipped.
Markdown/CSV names or headers only disambiguate verified text, never binary files.

Fetch each requested URL once. Resolve page links relative to the final URL after
redirects and deduplicate saved responses by that URL. A document link redirected
to an already saved homepage creates no duplicate and no false document.
Known document links can be acquired from pages at the crawl-depth limit;
extensionless links follow normal page-depth limits and are classified on fetch.

Save Markdown pages with source metadata, PDFs under `website/pdfs/`, other
documents under `website/documents/`, plus
`linkedin-urls.md` and `linkedin-and-resume-links.md`. These are discovered
links and possible-resume hints, not verified person identities.

Failed or unsupported responses are logged and skipped and counted in the existing
`failed_pages` field. `documents_saved` counts all saved documents, including PDFs;
`pdfs_saved` retains its PDF-only meaning. Zero saved HTML pages raises `InfrastructureError` with provider `website`,
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
`--depth`, `--max-pages`, `--documents/--no-documents`,
`--max-documents`, `--max-document-mb` and `--respect-robots/--ignore-robots`.
The former `--pdfs/--no-pdfs`, `--max-pdfs` and `--max-pdf-mb` options remain
aliases for document controls. Python accepts `include_documents`, `max_documents`
and `max_document_mb`, with the former PDF arguments retained as aliases; explicitly
supplied document arguments take precedence. Configuration retains its existing PDF
key names for compatibility, now applying to the combined document downloads.
Existing snapshots are still reused without reclassification or automatic repair.

## References

- [Implementation](startup_website_import.py), [CLI](__main__.py)
- [Dataset paths and storage](../standards_and_architecture/SKILL.md#datasets-and-storage)
