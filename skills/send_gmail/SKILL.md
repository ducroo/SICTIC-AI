---
name: send_gmail
description: Email a complete Markdown insight through gws, using a helper to produce readable HTML with inline styling. Use when the requester has authorized email delivery.
---

# Send Gmail

Use the requester's provided email address and a descriptive subject. Follow
the conversation's email preference in [AGENTS.md](../../AGENTS.md#emailing-individual-insights).
If `gws` is unavailable, provide the insight in chat without offering email.
Send the complete content in the body, with no attachment. For a deep-dive
invitation, send to the requester, not the recipients listed inside it.

## Usage

1. Convert the Markdown file to styled HTML; the helper prints the path to a
   unique temporary file:

   ```bash
   email_html="$(conda run -n sictic-env python -m skills.send_gmail /path/to/insight.md)"
   ```

2. Only after successful conversion, send the HTML body:

   ```bash
   gws gmail +send --to 'recipient@example.com' --subject 'Insight title' \
     --html --body "$(cat "$email_html")"
   ```

Confirm sending only after `gws` reports success. Report failures; do not
automatically retry an uncertain send. Remove the temporary HTML file when done.

The helper uses `markdown-it-py` and Beautiful Soup from `sictic-env`. It applies
inline styling for typography, lists, code and tables, preserves Markdown links
and escapes raw HTML. `--output /path/to/email.html` selects an output path.
It only converts files; `gws` owns authentication and sending. There is no bulk
refresh or harness registration.
