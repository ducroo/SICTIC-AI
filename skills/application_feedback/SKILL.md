---
name: application_feedback
description: Draft and email feedback for one startup with a fresh submission_ready review to configured internal reviewers. Bulk refresh invokes it per Application-stage startup.
---

# Application feedback

One startup, one feedback email, one task for the reviewer.

## Inputs and outputs

`application_feedback(startup, *, email="send")` returns `list[InsightFile]`:
the full email content in `application-feedback-<startup>-<model>.md`, or `[]`
when there is no fresh review or no proposed concerns. The existing filename,
manual precedence and draft cache are preserved. Recipients proofread the draft
and send it to the applicant themselves.

## Workflow and dependencies

Bulk refresh invokes this single-startup operation after submission-ready.
It never runs a review or loops over applications. When a stored review exists,
synchronize the dataset and require a fresh review through
`submission_ready.latest_response(require_fresh=True)`. Missing or stale reviews
produce no draft and no email. Fresh means reusable for the current audit,
configuration, stage and indexed sources; it need not have been generated in
this invocation. A changed audit invalidates the older response when a newer
review run fails before completing its response.

Only `Send concerns to startup` gets a draft. The model receives only the stated
concerns, following `config/application_feedback/email_instructions.md`.
The greeting uses the stored Dealum startup name. SCREENER_SIGNATURE supplies
the signature, with `[Screener name]` as the fallback. The formatting reviewer
does not establish factual fidelity; the human reviewer checks the content.
Unchanged inputs reuse the draft; manual drafts retain precedence.

The comma-separated APPLICATION_FEEDBACK_RECIPIENTS controls internal delivery.
Empty or unset saves and returns the draft without sending. By default, a new,
changed or undelivered draft is sent in full through send_gmail, one email per
startup to all configured recipients. No email is sent to the applicant.
`email="off"` and `email="dry-run"` save and return the Markdown without sending
or recording delivery. Changing draft instructions redrafts without rerunning
the review, provided that review remains fresh.

## Delivery tracking and failures

Delivery receipts remain at
`storage/generated/application-feedback-runs/insights/email-delivery.json`.
The existing application/recipient keys and schema are preserved, including the
legacy `summary` field, which now records the draft path. Prior receipts prevent
duplicates after upgrade. Content and recipient changes are eligible again;
recipient ordering does not matter.

The shared lock covers the decision, send and acknowledgement. An attempt is
recorded as uncertain before sending. Success records sent. Uncertain deliveries
are logged and held for inspection, while the draft is still returned and other
startups continue normally. Check Sent mail before marking an uncertain entry
sent or removing it to permit a new attempt; stop the scheduled job while doing
so. A missing gws binary is known to precede delivery and permits a later retry.
Other failures are not retried automatically. Unreadable receipts, invalid review
contents, synchronization errors and generation/send failures propagate.

## Usage

```bash
conda run -n sictic-env python -m skills.application_feedback --startup "Example Startup"
conda run -n sictic-env python -m skills.application_feedback --startup "Example Startup" --email dry-run
```

The nightly schedule only needs bulk_refresh. Replace SCREENER_EMAILS with
APPLICATION_FEEDBACK_RECIPIENTS on the runtime host before enabling delivery.
No separate distribution command remains. This skill has no harness command.

## References

- [Implementation](application_feedback.py), [CLI](__main__.py)
- [Delivery receipts](delivery.py)
- [Submission review](../submission_ready/SKILL.md)
- [Email sending](../send_gmail/SKILL.md)
