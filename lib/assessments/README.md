# Public deterministic assessment core

`lib.assessments` is a pure, synchronous contract boundary. It accepts six
already prepared values and returns a validated report:

```python
build_assessment(
    startup_id,
    source_snapshot,
    methodology,
    classification,
    evidence,
    findings,
)
```

The core does not resolve startup names, read storage, discover or ingest
documents, search source collections, call models, calculate an aggregate score, or emit
a recommendation or decision. Application-specific adapters are outside this
public contract.

## Closed source binding

`source_snapshot` accepts only `snapshot_id`, `startup_id`, `scope_id`, and a
sorted `inventory` of `{document_id, sha256}` records. Inventory records use
lowercase SHA-256 digests. Evidence accepts only an ID, snapshot/startup
binding, inventory `document_id`, and excerpt. Evidence is sorted by ID for
canonical output; unknown source fields and unbound documents are rejected.

## Methodology policy

The published methodology schema defines the classification vocabulary,
confidence vocabulary, tri-state applicability vocabulary, applicability rules,
variants, evidence-reference policy, and ambiguity/override policy. Missing applicability values resolve
through each check's configured default. `unknown` is always unresolved and
keeps the report incomplete. An uncertain classification uses the configured
`general_variant`; when no fallback exists, all sections remain unassessed.
When `allow_unreferenced` is false, every evidence record must be referenced by
a finding, classification, or applicability decision; when true, unused
evidence is retained in the canonical report.

Applicability input is a structured decision record with `state`, a policy
`basis`, snapshot-bound `evidence_ids`, and provenance. Non-default and
excluding decisions require evidence; classification always carries bound
evidence IDs and provenance when it selects a variant or applicability policy.
An all-`not_applicable` report is complete only when every exclusion is
explicitly justified and evidence-bound.

Finding input must contain an explicit producer `{id, version, config}`. Each
finding has a state, evidence references, and validated follow-up questions.
No list-only producer fallback exists.

## Identity and rendering

The persisted report separates:

- `identity.cache`: pre-execution cache key and normalized input components.
- `identity.content`: post-execution content digest and reconstructed report
  components, including source, methodology, classification provenance,
  evidence, producer/config, findings, selected variants, completeness,
  sections, schema, and renderer identities.

`validate_report()` reconstructs every component from persisted report content
and rejects mutations, stale digests, reordered persisted arrays, or mismatched
sections. `canonical_json()` returns stable compact JSON.

`render_assessment_markdown()` always renders the four compatible sections:
Team, Business opportunity, Product, and Documentation. Each check includes
its label/ID, applicability, state, summary, evidence excerpts, and follow-up
questions. Section states distinguish `assessed`, `missing`, `unknown`, and
`not_applicable`. Markdown text is normalized and escaped; report content is
never interpreted as markup.

The schemas in `config/assessment_engine/` are published contract artifacts
and are loaded during runtime validation. Fixtures and reports in
`tests/assessments/test_engine.py` are synthetic and contain no application
source material.
