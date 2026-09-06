---
name: ranking
description: Compare stored profiles against an objective using the shared ranking engine. Use its structured rows or Markdown adapter for expert search, potential investors, event advocates, and startup suggestions.
---

# Ranking

Rank supplied profile content and explain the finalists.

## Inputs and outputs

- `ranking_top_k(objective, all_profiles, top_k=16, batch_size=16)` accepts an
  ID-to-content mapping and returns `(ranked_items, actual_count)`; items contain
  `id`, `text` and one-based `rank`. Empty input returns `([], 0)`.
- `ranking_rationale(objective, ranked_items)` adds each item's `rationale`
  in place, preserving IDs, ranks and order.
- `rank_person_rows(...)` returns rows with `rank`, `full_name`,
  `email_addresses`, `linkedin_id` and `rationale`.
  `ranking_persons(...)` renders those rows as a Markdown table.
  Both default to `top_k=16`, `skill="investor_profile"` and
  `member_dataset="sictic-members"`; omitted `source_datasets` uses that dataset.

The person adapters accept optional `candidates` and `optout` lists of names,
emails or LinkedIn IDs. Omitted or empty candidates select the existing roster.
Explicit selections are matched to canonical people, then deduplicated.

## Workflow and dependencies

Read the roster through the synchronous `lib.people.discovery.persons_in_dataset`
reader and select preferred stored profiles with `select_insights`.
Person ranking requires LinkedIn IDs. Apply candidate selection and opt-outs
before reading profile content. Names, emails and IDs in output rows come from
canonical `Person` objects; the model supplies ordering and rationales.

The bucketed tournament shuffles candidates, compares batches, progressively
retains stronger buckets, then ranks the survivors together. Selection is
approximate and can vary between runs; it does not guarantee the global best
`top_k`. Intermediate batches default to 16; the final comparison can exceed
that size. Return at most the requested number, limited by available survivors.

Keep domain objectives in the calling skill's configuration. This package owns
`ranking_top_k` and `ranking_rationale` prompts and schemas. Use shared
`generate_json` and its `Review` mechanism. Ranking schemas restrict IDs to the
supplied candidates. The existing ranking reviewer removes duplicate IDs and
appends missing IDs in input order; unexpected IDs require correction. Rationale
validation rejects missing, duplicate or unexpected IDs and blank explanations.

## Side effects and failure behavior

The engine calls models but does not discover people, refresh profiles, ingest
documents, save insights or cache completed rankings. Callers own these decisions.
Ranking orders the supplied candidates; domain eligibility must be resolved by
the caller when strict exclusion is required.

Unknown explicit candidates, missing explicitly requested profiles, duplicate
profile IDs across source datasets, or an empty eligible profile pool raise.
With default roster selection, people without LinkedIn IDs or stored profiles
are skipped. Unresolved opt-outs log a warning. Configuration, generation and
validation failures propagate.

## Usage

Use the owning workflow's harness command for normal work. This utility has no
harness command or bulk-refresh registration. For direct debugging:

```bash
conda run -n sictic-env python -m skills.ranking --target persons --objective "Expertise in B2B SaaS sales" --top-k 16
```

## References

- [Person adapters](ranking_persons.py)
- [Tournament and ID review](ranking_top_k.py), [rationale generation](ranking_rationale.py)
- [Shared contracts](../standards_and_architecture/SKILL.md#ranking-workflows)
