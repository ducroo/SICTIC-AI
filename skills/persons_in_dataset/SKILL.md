---
name: persons_in_dataset
description: Discover startup founders and employees from the full parsed dataset, company website, web search and LinkedIn. Generate a refreshable roster; a deal-lead manual roster always takes precedence.
---

# Persons in dataset

Create the person roster before generating individual profiles.

## Inputs and outputs

The async `persons_in_dataset(dataset_name)` returns `list[InsightFile]`:
the manual, reusable generated, or newly generated roster, or `[]` if no
supported people are found. Its async `persons_in_dataset_as_person_objects`
adapter shares the workflow and returns `list[Person]`, retaining gathered
evidence in memory when discovery runs. Stored tables retain the three columns
`full-name`, `linkedin-id`, and `email-addresses`.

Generated files use the configured model's normal InsightFile suffix. Their
introductory reminder contains the actual generated and manual filenames:
deal leads must rename an edited roster to the manual filename to preserve it.
An existing manual roster, including an intentionally empty table, wins.
Existing manual rosters are not migrated, deleted or automatically regenerated.

## Workflow and dependencies

1. Resolve registered LinkedIn requests in one shared resolver pass: collect
   completed runs, resume running requests and submit open ones as needed.
   Expected pending/failed-profile service errors are logged and mark discovery
   incomplete; confirmed not-found profiles remain valid sparse inputs. This
   precedes roster lookup. Manual rosters still win when enrichment is unavailable.
2. Use the standard reusable-insight lookup once: manual first (including empty
   manual tables), otherwise a fresh generated roster. In addition to
   indexed revisions, its configuration key includes shared source-file hashes,
   discovery configuration, startup aliases and installed NER package versions.
   New raw LinkedIn JSON
   therefore invalidates reuse even before its indexed revision changes.
3. On a miss, synchronize and call the public startup-profile workflow, which
   applies its own manual/freshness selection. Supply its returned content to
   every person-selection LLM prompt. This skill does not separately look up
   startup-profile artifacts or reproduce their configuration keys.
4. Examine all current sources' available parsed Markdown using shared source
   enumeration and chunking. Local spaCy NER extracts candidate names; shared
   helpers extract emails and personal LinkedIn URLs. Retain source/page evidence
   in `Person.mentions`. LinkedIn documents are consumed as structured profiles.
   After shared identity merging, rank names by the sum of `1/n` across their
   source documents, where `n` is the number of distinct named candidates in
   that document. Each name counts once per document, independent of occurrence
   or page count. Keep the top `ner_max_candidates` (default 30); ties sort by
   name and canonical identifier. Explicit LinkedIn IDs and email candidates
   survive independently. The extractor itself still returns the full inventory.
5. Select an unambiguous website documented in the dataset. If no website
   snapshot exists, use the existing website-import skill with configured crawl
   limits and no PDFs, then synchronize and scan the resulting source material.
   Existing website snapshots are reused. Missing/ambiguous URLs are logged.
   Names from imported `website/` sources survive the NER cutoff. Cached profiles
   and company-wide LinkedIn search discoveries are also independent of the cutoff.
6. Make one company-wide query through the LinkedIn module and shared Apify-backed
   web search, looking for founders and employees associated with the startup.
   There are no per-person searches and no separate general web search. The
   configured result limit defaults to 10. Retain returned profile IDs and snippets
   as unverified evidence; names without IDs remain valid dataset candidates.
   Resolve candidate LinkedIn IDs through the existing cache and registry.
   Expected acquisition errors are logged and mark newly generated rosters
   incomplete; successful enrichment and outstanding registry requests are retained.
7. Synchronize acquired profiles and retrieve a small supplementary set of team
   chunks. Condense structured LinkedIn employment history locally; no preliminary
   person-profile generation is performed.
8. Reconcile candidates using shared JSON generation and schema validation.
   The LLM returns `existing_persons` selected from candidate records and
   `additional_persons` found in the supplied context/passages, each with names,
   emails and LinkedIn IDs. For existing people, use standard Person matching
   against the combined candidate pool. Exact LinkedIn-ID matches exclude weaker
   name/email matches. If unmatched, retry without the returned
   LinkedIn ID. Discard still-unmatched existing people. Complement a single
   match using Person.merge, with the candidate's ID taking precedence (including
   an empty ID). For ambiguous matches retain copies of every matching candidate,
   with their own contacts and evidence, and log the ambiguity. Do not mutate
   input candidates. Shared merging prefers the matching LinkedIn profile's
   structured name over NER name variants. Additional people are accepted as returned, with schema
   validation and normal Person normalization only; no evidence-occurrence or
   candidate-match requirement. Merge both lists through shared Person logic,
   preserving distinct LinkedIn IDs. Discard objects without a canonical Person
   identifier before saving the usual three-column roster.

The first priority is founders and employees; other associated people and former
employees may remain. Generic mailboxes and unrelated incidental mentions are
excluded by the reconciliation instructions. Name recognition and company-name
matches are candidate evidence, not proof of identity or affiliation.

For `sictic-members`, preserve the original workflow: return an existing manual
roster, otherwise create a manual roster from the local LinkedIn cache only.
No NER, web search, profile fetching or startup profile is used on that path.
Other non-startup datasets can use local discovery and LinkedIn evidence without
calling startup-specific profile, website or company-search workflows.

## Cost, side effects and failure behavior

spaCy runs locally and is installed unpinned through `environment.yml`.
`install.sh` downloads a compatible version of the configured NER model.
A missing model fails clearly; it never triggers an automatic LLM fallback.

Discovery defaults to at most three reconciliation batches, normally one,
with one short source-linked evidence excerpt per candidate and bounded relevant LinkedIn
descriptions. All employment entries are retained. Supplementary retrieval is
limited separately; it is not the exhaustive discovery mechanism. Batch limits
are checked before generation, and exceeding them raises instead of dropping
candidates. Shared generation correction/transient retries may add provider
attempts. Startup-profile generation and document ingestion have their own costs.

Source acquisition, synchronization and generation can write dataset files,
parsed documents, the index, LinkedIn registry state and generated insights.
Pending scraping keeps its existing actor run IDs in the shared registry and
is collected on a later invocation. Logging reports progress and errors;
expected external-service failures allow generation from available evidence.
Add a visible `INCOMPLETE` notice at the top of these rosters and save them through
the normal `InsightFile.save()` API. The notice is for the deal lead; it does not
affect reusable selection. Normal freshness and manual precedence still apply,
including invalidation when newly imported LinkedIn source files change.
There is no retry timer, automatic pause state, or subscription management.
Programming errors, invalid responses, ingestion and save failures still propagate.
Website imports with no saved HTML are logged and discovery continues with dataset
evidence. Partial crawls use the saved pages. Both cases mark new roster Markdown
incomplete; unrelated website errors still propagate.

No supported people leaves the roster absent, or leaves prior artifacts
unchanged. Invalid roster input raises. Automated discovery never writes a
startup manual roster, so a manual file created during discovery is preserved
without a final manual-file recheck.

Shared roster readers remain read-only: manual first, otherwise an existing
generated Markdown roster. They do not establish freshness or perform discovery.
Generated discovery JSON is not a roster input. Run this workflow explicitly
or through the declared bulk dependency to refresh before profiling. The skill
composes startup-profile itself after its cache check; its registry entry does
not introduce an eager startup-profile prerequisite.

Website/search changes alone do not trigger a refresh while the dataset and
other cache inputs remain unchanged. Startup-profile edits or configuration
changes alone also do not invalidate the roster: roster reuse is checked before
calling that skill. Local NER can miss or misclassify names;
the supplementary team evidence and final reconciliation reduce that risk but
do not guarantee exhaustive discovery. Weighted NER ranking can still exclude
rarely mentioned team members and retain false person detections. It ranks
candidates, not affiliation confidence; the final LLM determines affiliation.
Additional-person identity fields are not independently verified. Existing-person
matching can still be ambiguous, and this workflow deliberately favors retaining
all matching candidates over losing a potentially relevant person.

## Usage

```bash
conda run -n sictic-env python -m skills.harness /persons_in_dataset "<DATASET>"
```

The direct CLI accepts `--dataset` instead of a positional dataset.

## References

- [Workflow](persons_in_dataset.py), [bounded reconciliation](reconciliation.py)
- [Discovery configuration](../../config/persons_in_dataset/discovery.json)
- [Local person extraction](../../lib/people/extraction.py)
- [LinkedIn condensation](../../lib/people/linkedin/evidence.py)
- [Shared roster and parsing contracts](../standards_and_architecture/SKILL.md#authoritative-roster-and-table-parsing)
