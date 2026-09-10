---
name: deep_dive_invitation
description: Create a review-only Markdown deep-dive invitation for Joëlle from a Dealum startup and supplied contacts. Use for invitation preparation; never send the email or create a Gmail draft.
---

# Deep-dive invitation

Prepare recipient reconciliation and an invitation for human review.

## Inputs and outputs

The async `deep_dive_invitation(startup, founders=None, investors=None)` takes
lists of canonical `Person` objects and returns one `InsightFile` in a list,
named `deep-dive-invitation-<startup>-<model>.md`. `parse_people_csv` adapts
comma-separated names, emails or `Name <email>` entries.

For pasted Dealum Funding-tab text, extract contacts from Internal and External
under FUNDING INTERESTS. Preserve names and emails, including name-only
organizations; ignore round amounts, tags and interface text. Do not invent
contacts. Ask for the exact startup name/code only when unclear.

## Workflow and dependencies

Resolve the startup slug through shared startup identity and look for a reusable
invitation before running dependencies. Manual invitations always win; generated
invitations require matching indexed revisions for the startup and `sictic-members`,
plus matching template/settings and supplied contacts. A cache hit returns immediately
without importing, synchronizing, profiling, reading member preferences or ranking.

On a cache miss, import Dealum data, request normal `startup_profile`, read member preferences,
then request `expert_search`. Existing member rosters and investor profiles are
required; the invitation does not discover people. It has no bulk registration.

Supplied contacts are authoritative. Investor reconciliation tries exact email,
then LinkedIn ID, then normalized-name matches, not general fuzzy matching.
Investor email priority is the supplied address, then the matched member's
`@investor.sictic.ch`, `@sictic.ch`, then another stored address. Founder emails
can come from supplied contacts and the Dealum application contact; missing
addresses produce placeholders. Interested-investor Funding-tab extraction is
not automated, so the draft always includes a verification notice.

Interested investors with an address remain in Cc even with preference `none`;
missing addresses create notices and are omitted until completed. Exclude interested
members from Bcc selection after expert search; only preference opt-outs are
passed as expert-search exclusions. Changing interested investors therefore does
not change the ranking request. Match Cc recipients by existing member identity
as well as email, so alternate addresses do not duplicate recipients across Cc
and Bcc. Apply this filter before the Bcc limit. Configuration currently requests
16 candidates and selects at most 10 usable experts. Bcc excludes addresses already
in To/Cc; experts appear only in Bcc, not as named rows in the email body.

Render the configured template mechanically after reconciliation. Cache freshness
uses recorded indexed revisions, so unindexed source changes and direct edits to
member preferences, stored contacts or expert reports do not independently invalidate
the invitation. Dependency outputs are not included in its cache key. Generated
drafts using the previous key are regenerated once; manual precedence is unchanged.

For an application code that cannot resolve locally to the startup dataset,
Dealum import must resolve the canonical slug first. Check the resolved dataset
for a reusable invitation before executing the remaining dependencies.

## Side effects and failure behavior

Dependencies may import, synchronize, generate profiles and rank experts. Save
only a review artifact: do not send messages, create mail drafts or change stages.
Missing/ambiguous contacts can become visible review notices; dependency and
generation failures propagate. Preserve the configured recipient precedence and
manual output selection.

## Usage

```bash
conda run -n sictic-env python -m skills.harness '/deep_dive_invitation --startup "<EXACT_NAME_OR_CODE>" --founders "Jane Founder <jane@example.com>" --investors "Nina Member <nina@example.com>"'
```

The direct CLI uses the same plural `--founders` and `--investors` options;
both are optional.

## References

- [Implementation and recipient precedence](deep_dive_invitation.py)
- [Template and settings](../../config/deep_dive_invitation/)
- [Member preferences](../member_preferences/SKILL.md)
- [Expert search](../expert_search/SKILL.md)
