---
name: application_feedback
description: Draft the English feedback email for one startup from its latest submission review, for the SICTIC screener to proofread and paste into Dealum. Use after submission_ready; bulk refresh runs it for Application-stage startups.
---

# Application feedback

Draft the feedback email for one startup from its stored submission review.

## Inputs and outputs

The async `application_feedback(startup)` returns `list[InsightFile]`: the
draft `application-feedback-<startup>-<model>.md` in the startup's insights
folder, or an empty list when the review proposes no concerns. A draft only
contains that startup's own information.

`feedback_state(startup)` reads the latest review, its proposed action and the
draft that matches it, without generating anything. `None` as draft means no
concerns, or no current draft yet. [distribution_policy](../distribution_policy/SKILL.md)
uses it for the screener summary.

## Workflow and dependencies

Bulk refresh runs this step for Application-stage startups after
`submission-ready`, its registered dependency. A direct call uses the latest
stored review from `submission_ready.latest_response` without checking its
freshness, so run `submission_ready` first when the review must be current.

Read the action with `submission_ready.proposed_action`. Only `Send concerns to
startup` gets a draft: `generate_markdown` writes it in English, following
`config/application_feedback/email_instructions.md`. The greeting uses the
startup name of the latest Dealum application in the dossier. The model only
receives the concerns read with `submission_ready.stated_concerns`, not the
checklist, to reduce unsupported additions.

The draft is signed with `SCREENER_SIGNATURE` from `.env`, or with the
placeholder `[Screener name]` for the screener to replace when it is empty.
A reviewer requires between one and as many numbered points as there are
concerns, and that signature. These are formatting checks; they do not
establish that every concern is covered or that no concern was invented. The
screener must verify the draft against the review before sending it.

A stored or manual draft is reused while the instructions, the startup name,
the signature and the concerns are unchanged. Changing the instructions only
redrafts; it does not invalidate the review.

## Side effects and failure behavior

Reads the stored review and calls the configured model when a new draft is
needed. It does not access Dealum, send email or change any stage. A missing
review, a review without a proposed action, or a review that proposes sending
concerns without stating any raises; generation failures propagate.

## Usage

```bash
conda run -n sictic-env python -m skills.application_feedback --startup "Example Startup"
```

Normally bulk refresh runs this step. There is no harness command.

## References

- [Implementation](application_feedback.py), [CLI](__main__.py)
- [Email instructions](../../config/application_feedback/email_instructions.md)
- [Submission review](../submission_ready/SKILL.md)
- [Screener summary and email](../distribution_policy/SKILL.md)
