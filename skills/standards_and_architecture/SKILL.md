---
name: standards_and_architecture
description: The definitive source of truth for all coding conventions, environment constraints, and architecture layouts in the SICTIC-AI repository. The AI must review this skill before writing, modifying, or refactoring any Python code to ensure strict adherence.
---

# Standards and Architecture

This skill defines repository technical contracts. Read it before modifying code.

Follow the repository-root [AGENTS.md](../../AGENTS.md) for scope,
approval, implementation review and verification procedures.

See [Architecture and layout reference](references/architecture.md)
for the storage layout, module map and skill-directory example.

## Environment and common conventions

- Execute Python through the `sictic-env` Conda environment, bootstrapped
  from `environment.yml` by `install.sh`.
- The installer adds the repository root through a `.pth` file, so
  `skills` and `lib` imports work from any CWD without `PYTHONPATH`.
- Python files and skill packages use lowercase snake_case names.
  Dataset names are lowercase.
- Functions instantiate single-use dependencies unless sharing persistent
  state such as a database connection pool. Preserve existing optional client
  and storage injection points for testing and caller-owned resources.

## People: identity, evidence and workflows

### Canonical person object

Use [lib.people.model.Person](../../lib/people/model.py) between discovery,
enrichment, profiling and consumers. Preserve identity, contact, evidence and
profile fields; table-specific values belong in namespaced `adhoc_data`.

`Person` normalizes LinkedIn IDs and emails on construction. Reuse its module's
`normalize_email_addresses` and `extract_email_addresses`. Full-name cleanup
belongs to LinkedIn resolution's `sanitize_name`, not the constructor.

### Identity and matching

Use `Person.identifier`: **LinkedIn ID → first normalized email → slugified
full name**. `Person.display_name` is display text, not artifact identity.
Use `extract_linkedin_id` from `lib.people.linkedin` for URLs or ID inputs.

Reconcile through `Person.match_score`, `matches`, `find_best_match` and `merge`.
Confirm the match before merging; `merge` does not validate compatibility.
LinkedIn-cache resolution uses the stricter `find_cached_person` policy and
preserves explicit ID boundaries. Do not substitute general matching for it.
Preserve existing thresholds and workflow-specific rules for supplied contacts.

### Authoritative roster and table parsing

The [persons_in_dataset skill](../persons_in_dataset/SKILL.md) owns discovery
and initial roster creation. [lib.people.discovery](../../lib/people/discovery.py)
owns reading and rendering. Its synchronous readers never discover or enrich:

- `manual_persons_in_dataset`: absent file returns `None`.
- `persons_in_dataset`: absent file raises, directing callers to the skill.
- Both return `[]` for an intentionally empty valid table and reject invalid input.

The manual roster is authoritative. Preserve edits; generated discovery JSON
is not an alternative input. Empty discovery must not create a permanent empty
roster. Consumers must read it without implicit discovery; bulk refresh may run
the declared discovery dependency.
The discovery sources and `sictic-members` cache-only path belong in the skill.

Use the roster reader for roster inputs. For other person tables, use
[markdown_table_to_person_objects](../../lib/people/markdown.py) and preserve
additional columns under their tag.

### Person evidence gathering

Use [build_person_dossier](../../lib/people/dossier.py) for separate dossier and
incidental-mention lists. Its `get_filtered_chunks`, `person_in_filename` and
`is_personal_document` own retrieval filtering and document selection.
Dossiers exclude LinkedIn documents; profiling supplies that evidence separately.
Preserve source-document and page metadata; do not recreate selection in skills.

### LinkedIn retrieval and persistence

Use [LinkedInResolver](../../lib/people/linkedin/service.py):

- `get_cached_persons`: cached `Person` objects without external requests.
- `get_profiles`: enriches people; may fetch profiles, write stored files and
  registry state, or raise unresolved-profile errors.
- `get_profiles(allow_scrape=False)`: can still register missing profiles;
  it is not read-only.
- `get_all_persons`: display-name strings, not a roster or complete objects.

Use [LinkedInProfileStore](../../lib/people/linkedin/store.py); its `write`
applies shared `clean_linkedin_payload`. Stored LinkedIn JSON and generated
profile Markdown are distinct artifacts. Do not vary stored payloads by skill.

Use [LinkedInRegistry](../../lib/people/linkedin/registry.py) mutation methods
and their locked updates, not independent load–modify–save or direct JSON edits.
Use `linkedin_profile_not_found` to distinguish confirmed absence from failed or
pending retrieval. [diagnose_registry and import_profiles](../../lib/people/linkedin/maintenance.py)
own maintenance; copying JSON alone does not reconcile stored profiles and registry.

### Standard person profiles

[person_profile](../person_profile/SKILL.md) reads the roster, enriches LinkedIn
and gathers dataset evidence. Its standard prompt includes founder-trait
instructions; assess explicitly identified active founders and state insufficient
information where unsupported. Other people remain factual profiles.

`person_profile` returns `list[InsightFile]`; `person_profile_as_person_objects`
returns populated `list[Person]` from the same workflow. Explicit-name selection
and its current out-of-roster behavior are documented in that skill.

Pass `Person.identifier` to `InsightFile`: `<identifier>-<model>.md` with shared
filename normalization. Preserve manual profile precedence and the existing
`include_dataset_context` option. Do not add assessment or workflow suffixes.
Registry and direct team calls use the same standard profile settings and caches.

### Skill responsibilities

Use these skill documents for selection rules, prompts, CLI options and limitations:

| Owner | People workflow |
|---|---|
| [persons_in_dataset](../persons_in_dataset/SKILL.md) | Discovery and editable-roster creation. |
| [person_profile](../person_profile/SKILL.md) | Enrichment and standard individual profiles. |
| [linkedin_maintenance](../linkedin_maintenance/SKILL.md) | Missing-profile diagnostics and manual imports. |
| [member_preferences](../member_preferences/SKILL.md) | Roster identities and namespaced preferences. |
| [investor_profile](../investor_profile/SKILL.md) | Stored profiles plus manual track records/preferences. |
| [team_profile](../team_profile/SKILL.md), [team_profile_revised](../team_profile_revised/SKILL.md) | Team assessment using standard profiles. |
| [ranking](../ranking/SKILL.md), [suggested_startups](../suggested_startups/SKILL.md) | Selection from existing identities and profiles. |
| [deep_dive_invitation](../deep_dive_invitation/SKILL.md) | Supplied contacts, preferences and reconciliation. |
| [bulk_refresh](../bulk_refresh/SKILL.md) | Declared discovery/profiling dependencies. |

Do not assume all consumers support every identity fallback. In particular,
investor-profile eligibility currently requires a LinkedIn ID.

### Compatibility coverage

Use [Person tests](../../tests/models/test_person.py),
[table parsing](../../tests/people/test_markdown_people.py),
[dossiers](../../tests/people/test_dossier.py), and [LinkedIn tests](../../tests/linkedin/)
(identity, resolver, store, registry and maintenance).
[Discovery tests](../../tests/skills/test_persons_in_dataset_skill.py) and
[standard profile tests](../../tests/person_profile/test_person_profile_standard.py)
cover the roster/profile boundary.

## Insights: artifacts and freshness

Use `lib.insights.InsightFile` for managed insight artifacts.
It owns paths, filenames, model suffixes, selection and freshness
metadata. Skills must not recreate that logic or edit manifests.

### Naming, reading and saving

Pass the dataset, skill and canonical identifier to `InsightFile`.
Preserve existing identifiers and directory conventions. Use its
path properties and `content()` rather than reconstructing paths.

Use the supported `extension` argument for structured artifacts
such as JSON; not every insight is Markdown.

Save through `save()`. Manual precedence is applied during selection;
`save()` itself does not prevent overwriting a manual file.
Automated generation must preserve manual overrides.

### Selection and freshness

- `find(selection="reusable")`: manual override first, then a ranked
  model with matching configuration and indexed source revisions.
- `find(selection="any")`: preferred existing artifact without a
  freshness guarantee.
- `is_reusable()`: freshness of the exact file/model; does not select
  alternatives or apply manual-override precedence.
- `exists()`: file existence only.
- `find_all(selection="any")`: one preferred file per logical insight
  across startup/community datasets. Bulk reusable selection is unsupported.

Provide the relevant `source_datasets` and `config_key`, including
prompts, settings and supplied dependency content that affect the
result. Another insight changing does not automatically invalidate
this one.

Missing indexed source revisions prevent verified reuse. Saving may
still write the artifact without new freshness metadata.

Use `has_insufficient_context()` to recognize the exact
`INSUFFICIENT_CONTEXT` sentinel; this is separate from freshness.

### Consumers and outputs

Insight-producing skill APIs return a flat `list[InsightFile]`,
including cached results.

Use `select_insights` for read-only selection of preferred stored
artifacts; it does not guarantee freshness.

Use `dataset_from_insight` to reconcile files in a generated dataset.
It can remove obsolete target files, supports `dry_run=True`, and
does not itself perform indexing.

Use shared `strip_model_tag` and `insight_model_slug` helpers when
interpreting existing filenames.

## Checklist audits

Use `lib.batch_audit.batch_audit` for structured checklist assessment. Domain
questions, statuses, evidence restrictions and synthesis rules belong in the
owning skill's configuration.

`parse_checklist` accepts one H1 title, H2 chapters and H3 checks with self-contained
descriptions and optional terminal `**Keywords:**`. Generated numbers are
positional. Titles and original IDs remain in audit JSON; descriptions drive
per-check prompts and retrieval.

Explicit audit instructions replace the common instructions. Successful retrieval
with no hits still permits assessment from supplied context; missing evidence
and technical errors remain distinct. Use shared generation and validation.

The API returns one canonical JSON `InsightFile` per checklist. Use
`validate_audit_document` and `audit_errors` before final output, and
`json_to_markdown_table` for common tables. Structural validation does not establish
expected checklist coverage or citation accuracy. Synthesis belongs to the caller.

Audit reuse is per checklist; technical-error artifacts are ineligible.
The engine does not synchronize on a cache hit. Callers that require current
index state synchronize before lookup and document their additional dependencies.

## Ranking workflows

Use the existing `skills.ranking` engine to compare stored profiles directly.
`ranking_top_k` selects ranked IDs; `ranking_rationale` adds explanations while
preserving identity and order. `rank_person_rows` supplies structured results;
`ranking_persons` supplies the common Markdown table.

Resolve people through the existing roster and select stored insights through
shared readers. Person ranking currently requires LinkedIn IDs; output contact
metadata comes from canonical `Person` objects. The engine does not discover
people, refresh profiles, copy insights or index documents.

Keep domain objectives in their owning skill's configuration. Each workflow
documents its eligibility, prerequisites, cache dependencies, artifact identity
and failure behavior. Ranking orders supplied candidates; it does not enforce
domain exclusions. Reuse shared generation, validation and insight lifecycle
APIs. See the [ranking skill](../ranking/SKILL.md) for batching, ID recovery and
output adapters; keep those details there.

## Datasets and storage

### Paths and storage

Use `lib.datasets.paths` and `DatasetLocation` for dataset locations,
following `config/storage_domains.json`. Do not hardcode domain roots.

- `dataset_location` requires an existing dataset.
- `find_dataset_location` returns `None` when absent.
- `dataset_location_for_domain` resolves a location for creation in
  an explicit domain; it does not create the dataset.

Dataset slugs must be unique across domains. Use `list_dataset_names`,
`list_all_dataset_names` and `iter_domains` for enumeration.

Use `get_storage()` for ordinary application-data access, with relative
paths and no `..` components. Use domain abstractions such as
`InsightFile` for managed artifacts. Use `local_path()` when an
integration requires an OS path.

Application data uses `LOCAL_STORAGE_PATH`. `cache/` and `docling_data/`
use the configured machine-local storage root. Docling output is durable
parsed data, not disposable cache.

### Sources and document references

Use `list_source_files` and `snapshot_source_files` for ingestible
source enumeration and hashing. Preserve their shared exclusion rules.

Use `parsed_filepath` to map source documents to parsed Markdown.

`resolve_document_path` returns the closest source-document path and
a similarity score. It does not enforce a minimum score or reject
ambiguity; callers must apply their acceptance policy.

Preserve `Chunk` objects and document/page metadata. Use `Chunk.to_md()`
for standard evidence rendering and the shared page-marker and
spreadsheet helpers when processing those formats.

### Ingestion and synchronization

Use `sync_datasets` to reconcile sources, parsed documents and Qdrant
indexing. It can convert documents, call model services, replace
indexed content and remove obsolete derived data.

Conversion, chunking, embeddings, sparse encoding, indexing and
manifests belong to the shared pipeline. Do not recreate these stages
in skills or modify revision metadata directly. Preserve document
replacement ordering: write replacement chunks before deleting
obsolete chunks.

Synchronization returns `IngestionResult` objects with counts and
`IngestionFailure` details. Use `raise_on_error=True` when downstream
work requires successful ingestion; the default can log failures and
return partial results. The retained `force` parameter does not force
a rebuild.

Storage `refresh()` does not fetch external data in the current local
implementation. Application-storage mirroring is external to skills.
Existing source acquisition through Dealum/website imports is separate;
`ensure_startup_dataset` can perform a gated Dealum import and optional sync.
It can return a failure status while retaining local data unless strict errors
are requested. Document those existing side effects without adding new imports.

### Search and evidence

Use `dataset_search` for semantic retrieval. It synchronizes the dataset
before searching, so it is not read-only—even for an empty query.

Use `raise_on_error=True` when retrieval failures must remain distinct
from no matching evidence. Some retrieval failures otherwise return
an empty list; ingestion failures still propagate.

Reranking failures fall back to retrieval order, including when
`raise_on_error=True`. Retrieval, reranking and document-diversity
policies belong to the shared pipeline.

### Dataset state

Use `is_active_dataset`, `activate_dataset` and `archive_dataset`
for refresh-status markers. Archiving changes refresh eligibility;
it does not delete the dataset.

Use the `dataset_maintenance` skill for operational maintenance rather
than adding repair or rebuild logic to unrelated skills.

## Infrastructure

### Configuration and prompts

Use `load_repository_config(*sections)` for repository configuration
and `get_env_var` for environment settings.

Keep prompts, instructions and skill tuning parameters under `config/`.
Required configuration must fail clearly when absent; defaults belong
only to explicitly optional settings.

Use `config_cache_key` for effective configuration. Do not edit
compiled configuration caches directly.

### Model calls

Use `generate_markdown` and `generate_json` from
`lib.infrastructure.ai_text_generation`. Use the shared embedding
and reranking services for retrieval.

Resolve models and endpoints through `lib.model_config`.
Do not hardcode providers, endpoints or credentials in skills.

Text generation and embeddings must use the shared LiteLLM-backed
services. Skills must not call provider APIs directly.

Use the generation APIs' schema validation and `Review` mechanism;
reviewers are supported for both Markdown and JSON. Do not recreate
JSON repair or output-correction loops in skills.

Use `cacheable_prompt_prefix` for reusable shared context where
supported. Prompt caching does not replace insight freshness checks.

### Provider access and document conversion

Use `ApifyAdapter`, `DealumAdapter` and `WebSearchAdapter` for their
provider operations. Business decisions belong in domain libraries
or skills, not generic adapters.

Use dataset-scoped `QdrantAdapter` operations and preserve dataset
filtering within shared collections. Deleting a dataset is different
from `QdrantAdmin.delete_collection`, which deletes the whole
collection. Adapter initialization can reconcile legacy layouts;
do not assume it is read-only.

Use `document_conversion.convert_document` for individual conversion.
It returns `DocumentConversion(markdown, warnings)`. Preserve warnings,
normalization and shared format handling. Dataset ingestion owns
source selection, persistence and indexing.

### Scheduling and retries

Shared services own their scheduler integration. Skills must not add
duplicate scheduler leases around already scheduled services.

Register new capacity-controlled operations with `register_operation`
and a `JobProfile`, then execute through `scheduler.run`.
Keep scheduling metadata non-sensitive.

Preserve shared concurrency, lease and cloud-budget policies.
Do not modify scheduler state directly; use `snapshot()` for diagnostics.

Scheduler waiting and provider request timeouts are separate.
Use the shared transient-error retry mechanism and keep provider
retries distinct from output-correction attempts. Do not add
overlapping retry loops or silently retry permanent errors.

### Logging and errors

Use `get_logger(__name__)` from `lib.infrastructure.logging`.
Do not configure separate handlers in skills. Bootstrap modules retain
their existing logging initialization to avoid import cycles.

Log internal progress and failures. Reserve console output for CLI
results and user-facing errors.

At infrastructure boundaries, use `InfrastructureError` with kind,
provider, operation and recoverability metadata. Chain the original
exception. Domain validation may use standard exceptions.

Do not silently convert technical failures into missing evidence or
successful empty results. Preserve documented fallback behavior,
such as optional reranking fallback.

Core functions raise exceptions; they do not exit the process.
CLI wrappers use `lib.cli.run_command` for execution and error handling,
and `format_insights` for insight output. The existing Dealum batch CLI
implements its own per-startup error aggregation; this is a retained
implementation discrepancy, not a pattern for new wrappers.

### Known implementation discrepancies

Some existing adapters still expose standard or provider exceptions;
callers cannot assume every failure has InfrastructureError metadata.

Docling picture-description requests currently use a direct HTTP model
endpoint, conflicting with the LiteLLM rule. This requires separate
review; it is not authorization to introduce further direct model calls.

## Skills and orchestration

### Public APIs and structure

Keep one canonical workflow per skill and minimize public entry points.

User-facing workflows belong under `skills/`; shared infrastructure
and domain primitives belong under `lib/`. Preserve established
ownership, including the shared ranking package under `skills/ranking`.

Skill packages use snake_case names and contain `SKILL.md`.
Executable workflows normally have `__init__.py`, a thin `__main__.py`
and their implementation. Instruction-only skills need no CLI;
operational tools and shared utilities retain their established APIs.
Follow the [skill directory structure](references/architecture.md#skill-directory-structure).

Name the primary workflow API after the skill. Put the dataset argument
first where applicable. Preserve existing public parameter names,
defaults and return types; do not rename them merely for consistency.

Insight-producing APIs return `list[InsightFile]`, including cached
results. Explicit adapters may return domain objects while sharing
the same underlying workflow.

### CLI and harness

Keep Typer entry points in `__main__.py`. They parse and validate
arguments, call the public API and format results; business logic
belongs in the implementation.

Use `lib.cli.run_command` and `format_insights` where applicable.
Programmatic callers import the public API rather than invoking a CLI.

Slash-command exposure belongs to `skills.harness`.
Document supported commands in the skill's Usage section.
Harness registration does not imply bulk-refresh registration.

### Bulk-refresh registry

Register batch workflows in `skills/skill_registry.py` with their
callable, supported domains and prerequisite skill keys.

Bulk callables must support invocation with the dataset as their
single positional argument. Other required inputs must not be hidden
behind invented defaults just to make a skill batch-compatible.

Dependencies must reference registered skills and form an acyclic
graph. Let bulk_refresh expand dependencies and schedule eligible work;
do not reproduce its dependency graph inside individual skills.

A failed prerequisite causes dependent work to be skipped while
unrelated work can continue. Cross-domain dependencies apply to
matching prerequisite nodes within the selected dataset scope;
they do not automatically select additional datasets.

### Composition and compatibility

A skill may call another skill's public API to compose a workflow.
Direct calls do not automatically execute registry dependencies.

Respect each dependency's contract: some generate or refresh artifacts;
others only read existing inputs. Do not turn a read-only dependency
into implicit discovery or generation.

When both registry execution and direct composition invoke a
dependency, use compatible settings and reuse its managed artifacts.
Do not create competing variants or repeated regeneration.

Keep prompts and configuration with their owning skill. A new option
or dependency must be checked against existing callers, freshness
behavior and possible concurrent writes.

### Verification

For new or changed skills, update the relevant harness coverage and
contract tests. Verify public return types, CLI argument handling,
dependency order, failure propagation and artifact reuse as applicable.

Preserve explicit distinctions between insight-producing, operational
and instruction-only skills; not every skill belongs in bulk refresh.
