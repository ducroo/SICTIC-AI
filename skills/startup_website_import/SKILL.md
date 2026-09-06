---
name: startup_website_import
description: Import a startup website as Markdown pages and linked PDFs into its dataset. Use for an explicit public-website crawl.
---

# Startup website import

Collect website source material for later dataset ingestion.

## Operations and effects

The synchronous `startup_website_import(startup_name, url, ...)` returns
`WebsiteImportResult` with paths and counts, not insight artifacts.
It creates the dossier without activating it, then stages the crawl before
replacing `datasets/website/`.

The crawler queues same-host links, excludes configured low-value path segments,
and defaults to depth 1 and 50 HTML pages. PDFs default to enabled, with 20 files
and 25 MB per file. Robots rules are used when available; failure to load them
does not stop the crawl. Requests follow normal HTTP redirects.

Save Markdown pages with source metadata, PDFs under `website/pdfs/`, plus
`linkedin-urls.md` and `linkedin-and-resume-links.md`. These are discovered
links and possible-resume hints, not verified person identities.

Failed pages/PDFs are logged and skipped. Zero saved HTML pages raises and leaves
the existing website snapshot intact. Once a crawl succeeds, replacement removes
the old directory before copying staged files; this copy is not transactional.
Other dossier data is retained. There is no indexing, profile generation or
LinkedIn enrichment, and no harness/bulk registration.

## Usage

```bash
conda run -n sictic-env python -m skills.startup_website_import example https://example.org --depth 1
```

The direct CLI exposes `--depth`, `--max-pages`, `--pdfs/--no-pdfs`,
`--max-pdfs`, `--max-pdf-mb` and `--respect-robots/--ignore-robots`.

## References

- [Implementation](startup_website_import.py), [CLI](__main__.py)
- [Dataset paths and storage](../standards_and_architecture/SKILL.md#datasets-and-storage)
