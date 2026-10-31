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
  operations only. It shows new, changed or undelivered drafts with their Dealum
  link and full text, and lists drafts reused unchanged from an earlier run, the
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
to reduce unsupported additions. The draft is signed with `SCREENER_SIGNATURE`
from `.env`, or with the placeholder `[Screener name]` for the screener to
replace when it is empty. A reviewer requires between one and as many numbered
points as there are concerns, and that signature. These are formatting checks;
they do not establish that every concern is covered or that no concern was
invented. The screener must verify the draft against the review before sending.
Generated drafts are reused while their inputs and indexed sources are fresh;
manual drafts retain the standard precedence.

`email` decides how the summary reaches the screener: `off` (default), `dry-run`
or `send`. The recipients are the comma-separated `SCREENER_EMAILS` in `.env`;
they are checked before the review run starts. An email is only prepared when
there are drafts not yet delivered to these recipients, changed draft contents,
or failures. Preview and email-off runs never acknowledge delivery. Its HTML body
is the complete summary, including the full text of cached but undelivered drafts,
converted with `send_gmail`'s `markdown_to_email`. `send` uses the
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
summary path. A failed send also raises. A missing `gws` executable is known to
precede sending, so a later run may try again after setup is fixed. Other send failures and
interrupted attempts remain uncertain and are not automatically resent.

Delivery receipts are separate from InsightFile freshness, in
`storage/generated/application-feedback-runs/insights/email-delivery.json`.
They track the application, recipient set, exact draft content and summary path.
Updates use the shared file lock and atomic writer. A successful send acknowledges
the included drafts; changed content or recipients becomes eligible again.
For an uncertain entry, inspect Sent mail against the recorded summary. Once
confirmed, set its status to `sent`; if confirmed not sent, remove only that entry
before rerunning. Do this with the scheduled job stopped. Never clear uncertain
entries without checking: the message might already have been delivered.
Existing drafts without receipts are eligible for a first delivery after upgrade;
check any previously sent drafts before enabling the updated nightly sender.

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
