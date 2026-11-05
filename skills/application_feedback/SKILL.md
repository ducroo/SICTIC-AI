---
name: application_feedback
description: Screen one startup with submission_ready and email the configured internal screeners the decision that needs action, with a draft reply when the review has concerns. Bulk refresh invokes it for Application and Under Review startups.
---

# Application feedback

One startup, one screening decision, one email with the task for the screener.

## Inputs and outputs

`application_feedback(startup, *, email="send")` returns `list[InsightFile]`:
the draft reply to the startup in `application-feedback-<startup>-<model>.md`
when the review proposes sending concerns, otherwise `[]`. The existing
filename, manual precedence and draft cache are preserved. The screener
proofreads the draft and sends it to the applicant themselves.

## Workflow and dependencies

Call [submission_ready](../submission_ready/SKILL.md) for the startup and use
the response it returns, so audit selection and freshness stay in that skill.
In bulk refresh, the registry runs submission-ready first for Application and
Under Review startups, so this call reuses its import, index and review. A
startup without a response, for example one not found in Dealum, gets nothing.

Read the proposed action with `submission_ready.proposed_action`. Only `Send
concerns to startup` gets a draft. The model receives only the stated concerns,
following `config/application_feedback/email_instructions.md`. The greeting
uses the stored Dealum startup name. SCREENER_SIGNATURE supplies the signature,
with `[Screener name]` as the fallback. The formatting reviewer does not
establish factual fidelity; the screener checks the content. Unchanged inputs
reuse the draft; manual drafts retain precedence. Changing the draft
instructions redrafts without changing the review.

Every proposed action needs the screener: a progression such as `Move to Under
review` or `Move to Jury` is carried out in Dealum, and concerns are sent as a
reply. The email starts with the startup and the proposed action, followed by
the Dealum link, the complete review and, for concerns, the draft reply as a
copyable text block.

The comma-separated APPLICATION_FEEDBACK_RECIPIENTS controls internal delivery.
Empty or unset sends nothing. By default, a new or changed decision is sent
through send_gmail, one email per startup to all configured recipients. No
email is sent to the applicant. `email="off"` and `email="dry-run"` save and
return the draft without sending or recording delivery.

## Delivery tracking and failures

Delivery receipts remain at
`storage/generated/application-feedback-runs/insights/email-delivery.json`.
The application/recipient keys and schema are preserved; the legacy `summary`
field records the draft path, or the review path without a draft. The digest
covers the complete email, so the review and any draft are tracked together:
a new or changed decision is sent once, and an unchanged one stays quiet.
Recipient changes are eligible again; recipient ordering does not matter.
Receipts from versions that tracked only the draft do not match, so each open
decision is emailed once after the upgrade.

The shared lock covers the decision, send and acknowledgement. An attempt is
recorded as uncertain before sending. Success records sent. Uncertain deliveries
are logged and held for inspection, while the draft is still returned and other
startups continue normally. Check Sent mail before marking an uncertain entry
sent or removing it to permit a new attempt; stop the scheduled job while doing
so. A missing gws binary or a failed gws login is known to precede delivery,
so its entry is removed and a later run sends the email again.
Other failures are not retried automatically. Unreadable receipts, invalid review
contents, review failures and generation/send failures propagate.

## Usage

```bash
conda run -n sictic-env python -m skills.application_feedback --startup "Example Startup"
conda run -n sictic-env python -m skills.application_feedback --startup "Example Startup" --email dry-run
```

The nightly schedule only needs bulk_refresh. Replace SCREENER_EMAILS with
APPLICATION_FEEDBACK_RECIPIENTS on the runtime host before enabling delivery.
This skill has no harness command.

## References

- [Implementation](application_feedback.py), [CLI](__main__.py)
- [Delivery receipts](delivery.py)
- [Submission review](../submission_ready/SKILL.md)
- [Email sending](../send_gmail/SKILL.md)
