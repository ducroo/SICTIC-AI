---
name: application_feedback
description: Review all Dealum applications in the stage Application and draft feedback emails for the SICTIC screener, with one summary of the run. Use for the nightly screening run or to draft feedback for named open applications; reads from Dealum and sends nothing.
---

# Application feedback

Draft feedback emails that the screener proofreads and pastes into Dealum.

## Inputs and outputs

The async `application_feedback(startups=None)` returns a flat
`list[InsightFile]`: the run summary, then one draft per application with
concerns. `startups` limits the run to open applications whose name or Dealum
application code matches; a requested startup without an open application
raises before any review.

- **Drafts:** `application-feedback-<startup>-<model>.md` in the startup's
  insights folder. A draft contains only that startup's own information.
- **Summary:** one timestamped file per run under
  `storage/generated/application-feedback-runs/insights/`, for SICTIC
  operations only. It shows new or changed drafts with their Dealum link and
  full text, and lists drafts reused unchanged from an earlier run, the
  applications without concerns and the failures.

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
startup` gets a draft: `generate_markdown` writes it in English from the
review's concerns, following `config/application_feedback/email_instructions.md`.
A stored or manual draft is reused while the instructions and the review are
unchanged.

## Side effects and failure behavior

Reads Dealum (application list and attachments), imports and indexes the
submissions locally, calls the configured model and saves the review, drafts
and summary. It never writes to Dealum: no messages, no stage changes. It sends
no email and does not access Google Drive; Drive synchronization stays
external.

A failed application is recorded in the summary while the others continue.
After the summary is saved, any failure raises with the summary path.

## Usage

```bash
conda run -n sictic-env python -m skills.application_feedback
conda run -n sictic-env python -m skills.application_feedback --startups "Example Startup"
```

The nightly schedule calls the first command after bulk refresh. `--startups`
can be repeated. There is no harness command or bulk-refresh registration.

## References

- [Implementation](application_feedback.py), [CLI](__main__.py)
- [Email instructions](../../config/application_feedback/email_instructions.md)
- [Submission review](../submission_ready/SKILL.md)
