---
name: application_feedback
description: Review all Dealum applications in the stage Application and draft feedback emails for the SICTIC screener, with one summary of the run. Use for the nightly screening run, which can email the summary to the screener, or to draft feedback for named open applications; only reads from Dealum.
---

# Application feedback

Draft feedback emails that the screener proofreads and pastes into Dealum.

## Inputs and outputs

The async `application_feedback(startups=None, email="off")` returns a flat
`list[InsightFile]`: the run summary, the email preview of a dry run, then one
draft per application with concerns. `startups` limits the run to open
applications whose name or Dealum application code matches; a requested startup
without an open application raises before any review.

- **Drafts:** `application-feedback-<startup>-<model>.md` in the startup's
  insights folder. A draft contains only that startup's own information.
- **Summary:** one timestamped file per run under
  `storage/generated/application-feedback-runs/insights/`, for SICTIC
  operations only. It shows new or changed drafts with their Dealum link and
  full text, and lists drafts reused unchanged from an earlier run, the
  applications without concerns and the failures.
- **Email preview:** with `email="dry-run"`, the finished email with its
  recipients and subject as `email-preview-<model>.html` next to the summary.

## Workflow and dependencies

Fetch one Dealum application snapshot through `dealum_session` and select the
applications in the stage `Application`. Applications with an unknown stage are
skipped with a warning. Bulk refresh deliberately never downloads
Application-stage data, so this skill is the nightly review step for them.

For each application, run [submission_ready](../submission_ready/SKILL.md) with
its application code. That imports the submission from Dealum without
activating the dossier, checks it and saves its checklist and proposed action.
Bulk refresh keeps such an unmarked dossier unmarked while it is at stage
`Application` and activates it once it reaches an always-active stage.
Read the action with `submission_ready.proposed_action`. Only `Send concerns to
startup` gets a draft: `generate_markdown` writes it in English, following
`config/application_feedback/email_instructions.md`. The model only receives
the concerns read with `submission_ready.stated_concerns`, not the checklist,
so it cannot raise other points. A reviewer requires between one and as many
numbered points as there are concerns, and the `[Screener name]` sign-off.
A stored or manual draft is reused while the instructions and the concerns are
unchanged.

`email` decides how the summary reaches the screener: `off` (default), `dry-run`
or `send`. The recipients are the comma-separated `SCREENER_EMAILS` in `.env`;
they are checked before the review run starts. An email is only prepared when
the run has new or changed drafts or failures. Its HTML body is the complete
summary, converted with `send_gmail`'s `markdown_to_email`. `send` uses the
shared `send_html_email` from `lib.infrastructure.gmail`, which sends through
`gws` as described in the
[gws setup](../../spike/SETUP.md#email-reports-via-gws-optional-testing).

## Side effects and failure behavior

Reads Dealum (application list and attachments), imports and indexes the
submissions locally, calls the configured model and saves the review, drafts
and summary. It never writes to Dealum: no messages, no stage changes. Only
`email="send"` sends an email, and only to the screeners. It does not access
Google Drive; Drive synchronization stays external.

A failed application is recorded in the summary while the others continue.
After the summary is saved and the email delivered, any failure raises with the
summary path. A failed send also raises and is not retried, because the email
may still have been delivered.

## Usage

```bash
conda run -n sictic-env python -m skills.application_feedback --email send
conda run -n sictic-env python -m skills.application_feedback --email dry-run
conda run -n sictic-env python -m skills.application_feedback --startups "Example Startup"
```

The nightly schedule calls the first command after bulk refresh. Use
`--email dry-run` to check the email on a machine without `gws`. `--startups`
can be repeated. There is no harness command or bulk-refresh registration.

## References

- [Implementation](application_feedback.py), [CLI](__main__.py)
- [Email instructions](../../config/application_feedback/email_instructions.md)
- [Submission review](../submission_ready/SKILL.md)
