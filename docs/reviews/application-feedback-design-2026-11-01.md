# Application feedback: concerns and alternatives

Discussion notes for Marcel, 1 November 2026. These are design options, not an
approved implementation specification.

## Current position

The experimental move of feedback drafting into `submission_ready` has been
reverted. `application_feedback` again owns drafting, its prompt and reviewer,
the screener digest and delivery. Its sending behavior and delivery journal
remain unchanged. `submission_ready` returns the checklist and internal response.

Independent changes retained in the working tree:

- Bulk refresh discovers and screens open, unarchived Application dossiers
  without activating them. Application-stage defaults run only `submission_ready`;
  Under Review also includes it. Explicit skills without a dataset selector
  continue to use active datasets.
- Submission screening restricts evidence in its prompt to the selected
  application's dated Dealum folder. Retrieval itself remains dataset-wide.
- `InsightFile.refreshed` records a successful save on the returned object.
  It is in-memory only and does not replace delivery receipts.

## Concerns to address

1. **Two batch orchestrators.** `application_feedback` discovers applications,
   loops over them and invokes screening, while `bulk_refresh` now performs that
   screening too. Cached insights can avoid repeated generation, but separate
   commands still repeat orchestration and may repeat acquisition/index checks.
2. **Separate audiences.** The internal assessment explains status and action;
   the applicant feedback is a polite, actionable message. Keep these as separate
   files even if one skill generates both. Emails currently go to screeners,
   who review and paste the draft into Dealum, not directly to applicants.
3. **Draft fidelity.** The extra LLM call receives only the stated concerns.
   Its reviewer checks numbering and signature, not whether every concern is
   represented or unsupported claims were added. Human review remains necessary.
   Historical-application contradictions were an upstream screening problem;
   restricting the selected application's evidence improved the RideBase run.
4. **Cache boundaries.** Changing draft wording instructions should refresh the
   draft, not invalidate the internal assessment. Preserve filenames, manual
   precedence and shared InsightFile reuse.
5. **Delivery policy is broader than this skill.** Interactive insight requests
   and scheduled screening are two use cases. Recipient selection, consent,
   output selection and grouping should not be repeated across analytical skills.
   Selecting every skill must not implicitly authorize sending mail.
6. **Refresh and delivery are different.** The desired future rule allows an
   email after regeneration caused by data or prompt changes. The current journal
   instead deduplicates exact draft content per application and recipient set.
   Regeneration with identical text therefore does not currently cause another
   email. Decide persistence and retry behavior before changing that contract.

## Alternatives for orchestration and drafting

| Option | Approach | Tradeoff |
|---|---|---|
| Keep drafting in application_feedback | Bulk refresh screens; application_feedback consumes the relevant stored assessments and drafts/delivers feedback. | Smallest ownership change; needs reliable assessment selection and freshness checks before using stored results. |
| Move drafting into submission_ready | Screening returns checklist, internal response and optional feedback draft; a separate delivery step consumes the outputs. | One generation workflow; must keep assessment and draft cache dependencies separate and define draft-failure behavior. |
| Separate a drafting skill | Register feedback drafting after submission_ready as an explicit dependency; delivery remains separate. | Clear separation, but adds a skill and output-selection plumbing. |

## Alternatives for email delivery

- Retain the current screener-specific wrapper and its `off`, `dry-run`, `send`
  modes. This is the smallest immediate change.
- Introduce a reusable `email_policy` skill, called once at the outermost CLI
  or agent workflow. It receives returned insights, requested outputs and known
  requester/consent context, applies explicit rules without an LLM, and delegates
  conversion/sending to `send_gmail`. Bulk refresh would need to expose its job
  outputs. The policy must distinguish requested outputs from dependencies.

An environment variable can enable configured unattended delivery, but does not
by itself define recipients, consent, selected outputs or digest grouping.

Keep the existing delivery journal and scheduled command operational until a
replacement is ready. Preserve receipts and uncertain-send protection during
migration. Do not automatically resend uncertain deliveries. No email-policy
implementation or removal of application_feedback is being made now.
