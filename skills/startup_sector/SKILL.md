---
name: startup_sector
description: Classify a startup independently with Dealum, Dealroom, PitchBook and Startupticker taxonomies, using shared dataset evidence and provider-specific confidence and rationale.
---

# Startup sector

## Inputs and outputs

`startup_sector(startup)` returns one JSON `InsightFile` in a list, named
`startup-sector-<startup>-<model>.json`. The CLI and Python arguments are unchanged.
`startup_sector_as_dict(startup)` calls the same workflow and reads the validated
artifact; it does not run a separate classifier. Use this adapter when consuming
classifications: it resolves display names and derived fields for manual overrides.
The primary workflow still returns the original InsightFile, whose raw contents
are never changed merely by reading it.

The JSON has a `providers` object keyed by `dealum`, `dealroom`, `pitchbook` and
`startupticker`. Each provider record contains:

- `taxonomy`: provider, snapshot version, coverage status and sources.
- `result`: `classifications` by component, H/M/L `confidence`, a succinct
  `rationale` and up to three `evidence` references. Each component has a primary
  category ID (or null) and secondary IDs. Missing, inapplicable or uncovered
  components use null and no secondaries, with the reason in the rationale.
- `category_names`: display names resolved from the reference in Python.
- `derived`: parent IDs, matched reporting-group IDs and explicitly unevaluated
  reporting-group IDs. These are deterministic, not additional model judgments.

Dealum is the internal classification used by startup_profile. Classifications
for other providers come independently from source evidence, not translations
of the Dealum result. Software/Hardware/Biology/General belongs to dd_checks.

The primary industry is the narrowest supported principal customer application,
falling back to the offering itself when no application dominates. The primary
technology is the narrowest supported mechanism central to the offering's
distinctive capability. Secondaries retain other supported industries and central
enabling technologies, ordered from narrower to broader. Detailed selection
instructions belong in the configured prompt.
Descriptions may explain specialist relationships and boundaries against
neighbouring categories as local classification guidance, without adding formal
provider hierarchy links. Broader secondary categories should not merely repeat
what a selected specialist category already conveys. For the same technology
capability, select its most specific category rather than also listing the
underlying method; a broader selection needs evidence of a separate central
capability, explained in the rationale.
Primary selection follows the principal product benefit, not merely a narrower
label for a supporting feature, delivery form or component. Dated product and
customer evidence establishes current focus; unresolved conflicts with historical
applications, research projects or roadmaps must be disclosed with lower confidence.

## Reference configuration

One JSON per provider under `config/startup_sector/taxonomies/` supplies labels,
IDs, succinct descriptions with provenance, relationships, selection limits and
reporting rules. Local scope notes are not official provider definitions. IDs are
local stable keys; PitchBook retains historical printed numbering, not verified
current platform IDs. Do not relabel these snapshots as complete or current.

| Provider | Components in this snapshot | Coverage |
|---|---|---|
| Dealum | 53 industries; 102 technologies | Observed in 429 applications; incomplete official inventory. |
| Dealroom | 31 industries; 71 distinct subindustries with 121 parent links; 19 technologies; 50 example tags | Public taxonomy page takes precedence over the differing glossary subindustry list; tags are partial. |
| PitchBook | 218 industries with 41 derived industry groups and 7 broad sectors; 59 verticals | Hierarchy is historical 2017; current taxonomy unverified. |
| Startupticker | 8 reporting categories | Swiss Venture Capital Report 2026 categories. |

Industries and technologies allow a primary and up to two secondaries.
Dealroom subindustries also allow two secondaries; tags and PitchBook verticals
allow four. Startupticker has one category only. These limits are our selection
policy, not claims about provider platform limits.

Dealroom's 18 published reporting-group descriptions are retained. Execute only
rules whose combination semantics and required inputs are known. Mixed rules or
rules requiring uncollected fields remain unevaluated. Unknown components never
count as evidence of absence. PitchBook ancestors are derived from industry IDs.

## Workflow and dependencies

1. Prepare startup dossiers through `ensure_startup_dataset`, including canonical
   aliases and the existing gated Dealum import; strictly synchronize the dataset.
   Prepared generated datasets skip external preparation. Other domains are rejected.
2. Select manual or reusable JSON through `InsightFile.find(selection="reusable")`.
   Validate stored results before returning them.
3. On a cache miss, include the configured product, problem, benefit, customer and
   business-model sections from the latest local Dealum application when available.
   Use the importer’s snapshot inventory and canonical Markdown source, preserving
   its dated source reference. These company statements are evidence, not verified
   facts or an override of more current documents. Generated datasets and dossiers
   without an application rely on retrieval.
   Call shared `dataset_search` separately for the three configured
   queries: principal product/benefit, customers/application, and enabling mechanism.
   Split the existing 25-chunk budget across them (9/8/8), so technical passages
   cannot displace product and customer evidence in a pooled ranking. Shared
   retrieval still owns ranking and document diversity within each search.
   Deduplicate across searches by chunk ID, render passages with `Chunk.to_md()`,
   and retain the question headings in the shared evidence prefix. Missing search
   results are logged and explicitly marked; retrieval does not guarantee semantic
   completeness. The explicit application sections supplement the 25-chunk budget.
   Do not include or generate startup_profile.
4. Call shared `generate_json` once per provider, sequentially, with identical
   evidence in the cacheable prefix. The changing prompt contains only that
   provider's taxonomy and the classification instructions. Provider-side prefix
   caching is an optimisation, not a guarantee. Correction retries may add calls.
5. Derive each response schema from its reference: valid IDs, required components,
   selection limits, uniqueness, confidence and evidence requirements. The shared
   deterministic `Review` function checks primary/secondary overlap and valid
   parent-child choices. Shared generation handles validation and correction;
   there is no second LLM reviewer or custom retry loop.
6. Resolve names, ancestors and known reporting rules in Python. Save one combined
   JSON only after all four provider calls succeed. No partial insight is saved.

Schema and consistency checks do not establish citation accuracy or factual
support. Those remain grounded-generation requirements.

Freshness includes source revisions, every taxonomy reference, queries, settings,
prompts, schemas and structured-output configuration. There are no provider-specific
cache files. A changed reference rebuilds the combined artifact on the next call.
Generated files using the previous SICTIC schema follow normal invalidation.

## Manual compatibility

Manual artifacts remain authoritative and are never rewritten. New manual files
must retain each provider's taxonomy provenance and result. Edit the selected
category IDs; display names and derived parent/reporting fields may be left stale
or omitted. The structured reader recomputes those fields in memory from the
current references, preserving the original file and its provenance. Invalid IDs,
hierarchy relationships and other invalid assessment fields still raise.
Generated cached artifacts retain their strict consistency checks.

A legacy manual file with `sector`, `sector_confidence`, `rationale` and `evidence`
continues to be accepted against the legacy SICTIC schema and definitions. Its
retired `product_type` and `product_type_confidence` fields are ignored on reading.
It is returned unchanged and blocks provider generation, with an INFO log explaining
that the legacy override was retained. startup_profile continues to label it
**SICTIC sector**, not **Dealum industry**. Migration to the provider structure is
explicit manual work; the old label is never presented as a provider classification.
`sectors.json` and `legacy_response_schema.json` exist only for this compatibility.

## Side effects and failures

Preparation and retrieval can import Dealum data, parse, embed and index sources.
Optional acquisition failure retains its existing logged fallback; required
synchronization, retrieval and generation failures propagate. Previous insights
are preserved on failure, including when a later provider fails.

Successful retrieval with zero hits and no application proposition saves four explicit unresolved results with
L confidence and no evidence, without model calls. Normal freshness applies.
For user-supplied text or documents, use the shared temporary-dataset lifecycle:
prepare once, then pass the dataset name. Additional evidence for the same
investigation is added without wiping that dossier.

The registry remains unchanged: this is an optional standalone bulk skill for
startup/generated datasets and a prerequisite of startup_profile. No dependency
on startup_profile is introduced; dd_checks retains its own product classifier.

## Usage

```bash
conda run -n sictic-env python -m skills.startup_sector --startup avientus
conda run -n sictic-env python -m skills.harness '/startup_sector "avientus"'
```

```python
from skills.startup_sector import startup_sector, startup_sector_as_dict
insights = await startup_sector("avientus")
classification = await startup_sector_as_dict("avientus")  # Reuses the same insight.
```

## References

- [Implementation](startup_sector.py), [validation and derivation](taxonomy.py), [CLI](__main__.py)
- [Provider references](../../config/startup_sector/taxonomies/)
- [Instructions](../../config/startup_sector/llm_instructions.md), [queries](../../config/startup_sector/queries.json)
- [Standards](../standards_and_architecture/SKILL.md), [startup_profile](../startup_profile/SKILL.md)
