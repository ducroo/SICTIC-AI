---
name: deep_dive_invitation
description: Create a review-only Markdown deep-dive invitation for a Dealum startup. Use when Joëlle provides a startup and founder or interested-investor contacts, including unstructured text copied from Dealum's Funding tab. Extract the relevant contacts from that text, invoke the Python workflow, and never send the email.
---

# Deep-dive invitation

Create a Markdown InsightFile for Joëlle to review. Never send the email and do
not create a Gmail draft.

## Input preparation

Ask for the exact Dealum startup name or application code when it is not clear.
The Python entry point accepts structured, comma-separated contacts:

```bash
conda run -n sictic-env python -m skills.harness -- /deep_dive_invitation \
  --startup "<EXACT_DEALUM_NAME>" \
  --founders "Jane Founder <jane@example.com>, John Founder <john@example.com>" \
  --investors "Nina Member <nina@investor.sictic.ch>, FONGIT"
```

Both `--founders` and `--investors` are optional and plural. Each entry may be
`Full Name <email>`, an email address, or a name. Use natural `First Last`
names; commas separate people.

When the user provides unstructured Dealum Funding-tab text, clean it before
invoking the Python workflow:

1. Begin at `FUNDING INTERESTS`.
2. Extract contacts from both `Internal` and `External` sections.
3. Keep full names and email addresses. Preserve name-only contacts such as an
   organization, but never invent an email or LinkedIn ID.
4. Ignore round descriptions, amounts, tags, telephone numbers, dates,
   documents, discussions, and interface labels.
5. Convert the result to the structured `--investors` value above.

Joëlle-supplied contacts, including contacts extracted from her pasted text,
remain authoritative. The workflow augments them from Dealum and
`persons_in_dataset("sictic-members")` without silently fuzzy-matching them.

## Workflow guarantees

- Dealum reconciliation must be reliable; Dealum import stops on no match or
  unresolved ambiguity.
- Founder addresses may come from Joëlle and Dealum. Missing addresses create
  a visible placeholder and review notice.
- Investor email priority is Joëlle, then Dealum when available, then a member
  `@investor.sictic.ch` or `@sictic.ch` address, then another member address.
- Interested investors remain in Cc even when their invitation preference is
  `none`.
- Expert search requests 16 candidates, excludes interested members and
  members whose `deep_dive_invitation` preference is `none`, and uses at most
  the first 10 usable experts.
- Anyone in To or Cc is never included in Bcc.
- Experts appear only as Bcc recipients, never as named rows in the email body.
- The draft begins with warnings and reconciliation details, followed by the
  email. The body template lives in `config/deep_dive_invitation`.
- Automatic Funding-tab extraction is not configured, so every draft includes
  a prominent verification notice.
