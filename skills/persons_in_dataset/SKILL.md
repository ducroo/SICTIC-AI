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
   discovery configuration, the context cap, startup aliases and installed NER package versions.
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
   Keep candidates through acquisition and shared identity merging. At prompt
   selection, each distinct document distributes weight 1 across its distinct
   candidates, including email-only identities. Sum those contributions per person;
   repeated mentions/pages in the same document do not add weight. Ties sort by
   name and canonical identifier. There is no early person-count cutoff.
5. Select an unambiguous website documented in the dataset. Call the canonical
   website-import skill, which owns the one-time snapshot guard and shared crawl
   configuration (including PDFs), then synchronize and scan newly acquired source material.
   Existing website snapshots are reused even for explicit URL calls. Missing/ambiguous URLs are logged.
   Website pages use the same document weighting as other sources; website and
   email evidence have no automatic-inclusion exemption.
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
8. Build one reconciliation prompt. Include all LinkedIn-ID candidates first,
   then remaining candidates in descending summed document weight until full.
   Use `OLLAMA_CONTEXT_LENGTH_MAX` as the context cap, reserving 25% for output,
   reasoning and retry overhead. LiteLLM's local model-aware token counter estimates
   input size including the shared JSON instructions/schema and response format;
   tokenizer fallbacks may be approximate for models it does not recognize.
   Log included/omitted candidates and estimated tokens. If startup/team context
   or LinkedIn candidates cannot fit, fail before generation for deal-lead review.
   Reconcile the selected evidence using shared JSON generation and schema validation.
   The LLM returns `existing_persons` selected from candidate records and
   `additional_persons` found in the supplied context/passages, each with names,
   emails and LinkedIn IDs. Convert both lists to Person objects and enrich each
   returned person from matching candidates through shared Person matching and merging.
   Preserve returned identities and cleaned names; never restore unmatched candidates
   or split a returned person into its original fragments. Exact LinkedIn matches
   can also collect matching ID-less fragments. Different explicit LinkedIn IDs
   never merge; if a returned person has no ID and matches several distinct IDs,
   enrich only from ID-less matches rather than choosing an ID arbitrarily.
   Candidate evidence, contacts and profile metadata are copied without mutating
   inputs. Person.merge retains structured LinkedIn profile-name priority.
   Unmatched returned people remain accepted. Deduplicate the resulting objects
   through shared Person logic and discard objects without a canonical identifier.
   No business reviewer or additional LLM call is used for this enrichment.


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

Discovery makes one logical reconciliation request, with one short source-linked
excerpt per candidate and bounded relevant LinkedIn descriptions. All employment
entries are retained. Supplementary retrieval is limited separately. There is no
batching, character cap or fixed person-count cap; lower-ranked non-LinkedIn
candidates are omitted when the token budget fills. Shared generation correction
and transient retries may add provider attempts. Startup-profile generation and
document ingestion have their own costs. Full-source extraction and identity
matching still occur before selection and can be expensive on very large websites.

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
matching can still be ambiguous; enrichment preserves explicit LinkedIn identity
boundaries and never restores unselected candidate fragments as roster entries.

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
