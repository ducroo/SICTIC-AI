---
name: distribution_policy
description: Email SICTIC insights by two explicit rules - the nightly summary of application feedback drafts to the configured screeners, and an insight to the person who requested it after they agreed. Use for every insight email; selecting or running skills never sends email by itself.
---

# Distribution policy

Decide who receives which insight by email, and send it through
[send_gmail](../send_gmail/SKILL.md).

## Inputs and outputs

- `screener_feedback(email="off")` returns `list[InsightFile]`: the screener
  summary and, for a dry run, the email preview.
- `requested_insights(insights, requester, *, requester_agreed)` emails each
  requested Markdown insight and returns `None`.

The screener summary is one timestamped file per run under
`storage/generated/application-feedback-runs/insights/`, for SICTIC operations
only. It shows new, changed or undelivered drafts in full, as copyable text
blocks with their Dealum link. It lists drafts whose delivery is uncertain,
unchanged drafts, applications without concerns, and applications that are not
ready. A dry run saves the finished email with its recipients and subject as
`screener-email-preview-<model>.html` next to the summary.

## Workflow and dependencies

**Screener feedback** runs once after the nightly bulk refresh, which reviews
the open applications and drafts their feedback. Fetch the Dealum application
list once and select the startups whose latest application, chosen by the
shared Dealum matching as in bulk refresh, is in the stage `Application`.
Unknown stages are skipped with a warning. For each, read the stored
review and draft with `application_feedback.feedback_state`. Nothing is
generated. An application without a review, or with concerns but no current
draft, is listed as not ready.

`email` is `off` (default), `dry-run` or `send`. The recipients are the
comma-separated `SCREENER_EMAILS` in `.env`, required for `dry-run` and `send`.
An email is only prepared when there are new, changed or undelivered drafts, or
applications that are not ready. Its body is the complete summary.

**Requested insights** implement the rule in [AGENTS.md](../../AGENTS.md#emailing-individual-insights):
an agent sends an insight only after the requester agreed, and only to that
requester. Send exactly the requested insights, not the dependencies a workflow
produced on the way. For a deep-dive invitation, send it to the requester, not
to the recipients listed inside it. Each insight goes in full in the body of its
own email, without attachment, with a subject from its first heading. All files
are checked before the first email is sent.

## Side effects and failure behavior

Screener feedback reads the Dealum application list, never writes to Dealum and
sends nothing to startups. Only `send` emails the screeners, through
`send_gmail`. A failed send raises.

Delivery receipts are separate from InsightFile freshness, in
`storage/generated/application-feedback-runs/insights/email-delivery.json`.
They record the application, recipient set, exact draft content and summary
path. Updates use the shared file lock and atomic writer, and an unreadable
file stops the run. Before sending, the included drafts are recorded as
`uncertain`; a successful send records them as `sent`. Changed content or
recipients make a draft eligible again. Preview and `off` runs never record a
delivery.

A missing `gws` program is known to precede sending, so its entries are removed
and a later run tries again. After any other send failure or an interrupted
run, the entries stay `uncertain`. Such drafts are never resent automatically:
the summary lists them under "Delivery uncertain", while all other drafts
continue normally. Check the Sent folder of the sender account against the
recorded summary. Then set the entry's status to `sent`, or remove only that
entry to have the draft included again. Do this with the scheduled job stopped.
Existing drafts without receipts are eligible for a first delivery.

Requested insights raise before sending when the requester has not agreed,
when there is not exactly one requester address, or when a file is missing or
not Markdown. A failed send raises and is not retried, because the email may
still have been delivered.

## Usage

```bash
conda run -n sictic-env python -m skills.distribution_policy screener-feedback --email send
conda run -n sictic-env python -m skills.distribution_policy screener-feedback --email dry-run
conda run -n sictic-env python -m skills.distribution_policy requested --to "requester@example.com" --requester-agreed "storage/startups/example-startup/insights/startup-profile-example-startup-model.md"
```

The nightly schedule calls the first command after bulk refresh. Use
`--email dry-run` on a machine without `gws`. Insight paths are absolute or
relative to the application storage, as printed in `RESULT_PATH` lines. There
is no harness command or bulk-refresh registration.

## References

- [Implementation](distribution_policy.py), [delivery receipts](delivery.py), [CLI](__main__.py)
- [Feedback drafts](../application_feedback/SKILL.md)
- [Email rendering and sending](../send_gmail/SKILL.md)
