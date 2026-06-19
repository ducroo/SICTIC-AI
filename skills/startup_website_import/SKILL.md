---
name: startup_website_import
description: Import a startup's public website into the startup dataset website folder as Markdown pages and linked PDFs.
---

# Startup Website Import

Use this skill to import a startup's public website into the normal SICTIC-AI
startup dataset folder.

The skill creates the startup dossier if needed, without activating the dataset
for bulk refresh. It stages the crawl locally first, then overwrites:

```text
storage/startups/<startup>/datasets/website/
```

It crawls the exact domain of the supplied URL only. By default it imports the
landing page and one internal layer, up to 50 HTML pages. Linked PDFs are
downloaded by default, up to 20 files and 25 MB each. It respects `robots.txt`
when available.

Pages are saved as Markdown with source frontmatter. PDFs are saved under
`website/pdfs/`. A `linkedin-and-resume-links.md` manifest lists LinkedIn
profile URLs and downloaded PDFs that may be resumes/CVs. A dedicated
`linkedin-urls.md` file contains only the LinkedIn profile URLs found while
crawling. Failed internal pages are logged and skipped; if no HTML page can be
saved, the existing website data is left unchanged.

## Usage

```bash
python -m skills.startup_website_import climease https://climease.com
python -m skills.startup_website_import climease https://climease.com --depth 2
python -m skills.startup_website_import climease https://climease.com --no-pdfs
```
