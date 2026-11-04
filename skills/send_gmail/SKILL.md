---
name: send_gmail
description: Render a complete Markdown insight as readable HTML with inline styling and send it through gws. Use for opted-in requested insight emails and application feedback delivery; the CLI only converts for previews.
---

# Send Gmail

Render and send insight emails. Follow the requester opt-in rule in AGENTS.md:
email only the requested insights, in full, to the requester, excluding workflow
dependencies. For deep-dive invitations, the recipient is the requester, not
the people listed inside the invitation. The application_feedback skill uses
this same sending API for its configured internal recipients. If `gws`
is unavailable, provide the insight in chat without offering email.

## Operations and effects

`send_gmail(markdown, recipients, subject)` sends the complete Markdown content
in the body of one HTML email, without attachment, through the shared
`send_html_email` from `lib.infrastructure.gmail`. It raises when `gws` fails.
A failed send may still have been delivered, so callers do not retry it
automatically.

`markdown_to_email(markdown)` renders the HTML. It uses `markdown-it-py` and
Beautiful Soup from `sictic-env`, applies inline styling for typography, lists,
code and tables, preserves Markdown links and escapes raw HTML.

## Usage

Convert a Markdown file to styled HTML to preview an email; the helper prints
the path to a unique temporary file:

```bash
conda run -n sictic-env python -m skills.send_gmail /path/to/insight.md
```

`--output /path/to/email.html` selects an output path. The CLI only converts
files; `gws` owns authentication and sending. There is no bulk refresh or
harness registration.

## References

- [Rendering](render_email.py), [sending](send_gmail.py), [CLI](__main__.py)
- [Application feedback](../application_feedback/SKILL.md)
