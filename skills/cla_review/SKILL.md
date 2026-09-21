---
name: cla_review
description: Review one convertible-loan term sheet from the lender's side, against the SECA CLA model term sheets and in the context of the startup's cap table, existing loans and SHA. Use before SICTIC members lend.
---

# CLA term sheet review

Identify the term sheet, extract its terms, judge them for a lender and show what they do in this company.

## Inputs and outputs

The async `cla_review(dataset_name, *, document=None, ticket=None, fresh=False)`
returns one Markdown report in `list[InsightFile]`, named
`cla-review-<startup>-<document>-<model>.md`, one per reviewed document. JSON
intermediates (`identification`, `extraction`, `assessment`, `conversion`,
`loan-context`, `sha-context`, `audits/<checklist>`) live under
`insights/cla-review/` and carry the document identity in their identifier.
`document` names the data-room path of the term sheet; omitted, the model
selects the most recent CLA term sheet and executed loans are context, not
candidates. `ticket` is the member's own amount and is part of the
configuration key, so a new ticket replaces the generated result for that
document. `fresh` bypasses generated reuse without deleting files or
overriding manual inputs.

**Slice 0 (current):** the contract above, `config/cla_review/settings.json`
with the lender-angle rules, the two SECA reference term sheets and the
fixture term sheet exist; the workflow does not. Calling the skill validates
the configuration and fails with a clear message. The slices are listed in
[docs/cla-review-design.md](../../docs/cla-review-design.md#7-slices).

## Workflow and dependencies

Two questions, one report. Question 1, the terms themselves: identify the
document, extract it with the shared `captable_build` CLA checklist
(`config/captable_build/cla_terms.md`, extended with term-sheet-only fields),
assess it from the lender's side with the rules in `settings.json`, and audit
it against the closest SECA reference through
[batch audit](../standards_and_architecture/SKILL.md#checklist-audits) with
lender-perspective checklists. Question 2, the terms in this company: the
member's conversion on the consolidated `captable_build` insight via
`lib.captable.model`, the existing loans compared (MFN, identical-terms
groups, 10/20 non-bank rules before and after N members), and the SHA and
articles for executability. The consolidated insight is read through
`lib.captable.insights.select_consolidated`; it is never generated
implicitly and the registry declares no prerequisite.

Every rule in `settings.json` carries value, source, status, effective date
and an `active` flag. Only rules with status `approved` may be active; an
inactive rule can raise an open question in the report but never a
judgment. Loading rejects an active rule that is not approved.

## Side effects and failure behavior

Preparation may import, convert and index documents. The review calls models
and saves intermediates and the report; it sends nothing. An absent or stale
cap-table snapshot yields insufficient-evidence findings for question 2;
malformed artifacts, failed path resolution and technical audit failures
remain errors. Slice 0 raises `ValueError` before any dataset work. The report
aids human review and is not legal advice.

## Usage

```bash
conda run -n sictic-env python -m skills.harness '/cla_review "<STARTUP>"'
conda run -n sictic-env python -m skills.harness -- /cla_review "<STARTUP>" --document "legal/cla-term-sheet.pdf" --ticket 25000
conda run -n sictic-env python -m skills.cla_review --startup "<STARTUP>" --document "legal/cla-term-sheet.pdf" --ticket 25000 --fresh
```

The direct CLI uses `--startup`; `--dataset` and `-d` remain compatibility aliases.

## References

- [Implementation](cla_review.py)
- [Design and slices](../../docs/cla-review-design.md)
- [Configuration, rules and SECA reference term sheets](../../config/cla_review/)
- [Shared CLA extraction checklist](../../config/captable_build/cla_terms.md)
- [Shared audit contract](../standards_and_architecture/SKILL.md#checklist-audits)
