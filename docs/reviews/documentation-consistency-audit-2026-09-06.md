# Documentation consistency audit — 6 September 2026

Current status: see the [documentation closeout](documentation-closeout-2026-09-06.md). The observations and proposals below retain their historical audit context.

Status: first-pass discrepancy register and improvement proposal, followed by the People documentation pilot recorded below. This report is not a new source of instructions. The original read-only audit changed no implementation or existing instruction document; the pilot changes documentation only.

The audit used local `main` at `1be1a27`, including the approved, uncommitted changes to `AGENTS.md`, the standards skill and its architecture reference. Findings describe this snapshot; they are not all regressions introduced by the recent work.

## Scope and evidence

Read all **27 SKILL.md files** (1,486 lines, of which 517 are standards), root `AGENTS.md`, the architecture reference and the revised-team decision reference. Inventoried **26 CLI modules, 21 registered harness commands, 14 bulk registry entries and 92 library Python modules**. Traced the main skill entry points and selected shared implementation, caller, configuration and test paths for the findings below.

The [companion inventory](documentation-consistency-inventory-2026-09-06.md) lists every skill, registration, candidate API and library module. Inventory coverage is complete for those surfaces; behavioral verification of every library routine and every prompt is **not** complete. Historical team-question registers remain design evidence, not governing instructions. Other repository guides and historical review reports need a later sweep.

Code establishes what currently happens. It does not, by itself, establish what should happen. Existing tests can preserve an unintended behavior. Where the intended contract is uncertain, the register requests a decision rather than prescribing a code or filename change.

Priority means review order: **P1** affects results, failures, identity or destructive operations; **P2** affects integration, configuration or clear instructions; **P3** affects maintenance and structure. “Decision” identifies an unresolved contract question; it does not request approval to fix anything in this audit.

## People pilot progress — 6 September 2026

The findings below retain their original observations. Current documentation has
been updated for `persons_in_dataset`, `person_profile`, `investor_profile`,
`team_profile` and `team_profile_revised`, plus the shared People standards and
the revised-team decision reference. Other categories and skill documents remain
outside this pilot; the companion inventory remains the original audit snapshot.

| Finding | Pilot outcome |
|---|---|
| F01 | Corrected the old team documentation to use the standard adapter and existing roster. Stale code comments are deferred to scoped code work. |
| F02 | Documented actual `names` input, all-roster selection, adapters and CLI differences. |
| F03 | Documented LinkedIn-only investor eligibility, existing source prerequisites and read-only selection. |
| F04 | Manual investor-output overwrite remains unresolved; the skill now discloses the conflict without legitimizing it. No code fix in this pilot. |
| F21–F22 | Removed repeated shared rules and applied a common structure to these five skills. Remaining documents await later iterations. |
| F27 | Documented the existing explicit unmatched-name path. No new rule permitting or forbidding it was introduced; any behavior change needs separate review. |
| F29 | Documented the original team's dependency-content cache limitation; changing it remains outside this pilot. |
| F30 | Corrected the decision reference: founder instructions are standard, assessment applies to active founders, and profile dependencies include LinkedIn enrichment. |

The shared People section decreased from 893 to 661 whitespace-delimited words
(about 26%). Investor documentation grew to cover previously omitted eligibility,
side effects and failure outcomes. Identity priority, filenames, manual-roster
precedence, explicit discovery, founder enrichment and registry configuration are
unchanged. No code, prompt, configuration or test file was edited.

Pilot verification: 41 existing People/discovery/investor/team regression tests
and all 11 documented CLI routes passed, with business APIs mocked for command
checks. File and heading links, frontmatter and section structure also passed.
The bundled skill validator rejects this repository's existing `snake_case`
names because it requires hyphens. Names were preserved; repository-aware
validation checks the established naming convention instead.

## Findings: behavior and integration

### F01 — P1 · Incorrect documentation · Team profiling still claims discovery

**Claim:** [team_profile/SKILL.md](../../skills/team_profile/SKILL.md), “Person Discovery & Profile Reuse”, says `person_profile(..., names=None)` discovers people.

**Evidence:** [team_profile.py](../../skills/team_profile/team_profile.py), `team_profile`, calls `person_profile_as_person_objects`; [person_profile.py](../../skills/person_profile/person_profile.py), `_person_profile_result`, reads the existing roster. Missing-roster behavior is covered by [standard person-profile tests](../../tests/person_profile/test_person_profile_standard.py).

**Action:** Correct the called API, describe roster reading and the missing-roster prerequisite, and remove the same stale discovery terminology from comments when that code is in scope. **Decision:** none; the user already established this contract.

### F02 — P2 · Incorrect/incomplete documentation · Person-profile input contract

**Claim:** [person_profile/SKILL.md](../../skills/person_profile/SKILL.md), “Inputs”, presents a single `name` string.

**Evidence:** [person_profile.py](../../skills/person_profile/person_profile.py), `person_profile` and its adapter, accept `dataset_name`, optional `names: str | list[str]`, and keyword-only `include_dataset_context`. Omitted names select the roster. The [direct CLI](../../skills/person_profile/__main__.py) permits omission; the [harness handler](../../skills/harness/harness.py), `_person_profile`, requires a person.

**Action:** Document the real Python signature and distinguish the existing CLI surfaces. **Decision:** none for documentation; making the harness accept all-roster calls would be a separate API change.

### F03 — P2 · Incorrect documentation · Investor-profile eligibility is overstated

**Claim:** [investor_profile/SKILL.md](../../skills/investor_profile/SKILL.md) says it combines “every generated person profile”.

**Evidence:** [investor_profile.py](../../skills/investor_profile/investor_profile.py), `_investor_profile_result`, reads the roster, selects members with LinkedIn IDs and filters files against those IDs. Email/name-only profiles are excluded. The [standards skill](../../skills/standards_and_architecture/SKILL.md), “Skill responsibilities”, already records this limitation; [investor tests](../../tests/skills/investor_profile/test_investor_profile.py) cover roster filtering and model variants.

**Action:** State eligibility and stored-input prerequisites in this skill; reference the shared identity contract. **Decision:** none; broadening eligibility remains outside this audit.

### F04 — P1 · Confirmed code/standard conflict · Investor generation can overwrite a manual investor profile

**Claim:** [standards](../../skills/standards_and_architecture/SKILL.md), “Naming, reading and saving”, requires automated generation to preserve manual overrides.

**Evidence:** In [investor_profile.py](../../skills/investor_profile/investor_profile.py), `_investor_profile_result` accepts a source named `<id>-manual.md`, derives `source_model="manual"`, and saves composed content to the corresponding **investor-profile manual file** when content differs. [InsightFile.save](../../lib/insights/file.py) writes manual files without overwrite protection. Thus an existing edited investor-profile manual file can be replaced when a manual person-profile source exists. This is a static, conditional code-path finding; no real manual artifact was modified or loss observed.

**Action:** Resolve manual output ownership before adding regression coverage and a fix. The current investor tests do not cover this case. **Decision:** yes—how should deterministic composition treat an independently edited manual investor profile?

### F05 — P1 · Confirmed mismatch; intent unresolved · Traction with missing evidence

**Claim:** [startup_traction/SKILL.md](../../skills/startup_traction/SKILL.md), workflow step 4, promises an error and no saved insight when context is insufficient.

**Evidence:** [dataset_chat](../../skills/dataset_chat/dataset_chat.py) returns its fallback sentinel when no chunks are retrieved. [startup_traction.py](../../skills/startup_traction/startup_traction.py) saves the returned string; it also substitutes “No relevant information found.” for falsey results. There is no insufficient-context rejection.

**Action:** Decide whether missing evidence should produce an artifact or a failure, then align documentation and a focused behavioral test. **Decision:** yes; do not silently bless the code or change its behavior.

### F06 — P2 · Incorrect documentation · Traction uses obsolete call syntax

**Claim:** [startup_traction/SKILL.md](../../skills/startup_traction/SKILL.md) shows `dataset_chat(..., questions=..., llm_instructions=...)`, nested config access after a section load, and a positional startup CLI argument.

**Evidence:** [startup_traction.py](../../skills/startup_traction/startup_traction.py) uses `queries` and `prompt`, reads `config["query"]` after `load_repository_config("startup_traction")`, and its [CLI](../../skills/startup_traction/__main__.py) takes `--startup`. `InsightResult` remains a valid alias for `list[InsightFile]`; that spelling is not a defect.

**Action:** Correct the examples and remove the repeated general architecture constraints. **Decision:** none.

### F07 — P1 · Incorrect documentation · DD chapter failures do not produce a partial final report

**Claim:** [dd_checks/SKILL.md](../../skills/dd_checks/SKILL.md), “Resiliency”, says failed chapters are recorded inside the Markdown report while remaining chapters continue.

**Evidence:** [dd_checks.py](../../skills/dd_checks/dd_checks.py), `chapter_by_chapter`, runs all chapter tasks, collects failures and raises if any failed. `dd_checks` then never reaches final-report saving. Successful internal JSON audits may already exist. [Chapter tests](../../tests/skills/test_dd_checks_and_batch_audit.py) cover concurrent execution and ordered results.

**Action:** Describe persisted intermediate artifacts, final failure and retry/reuse behavior separately. **Decision:** none to document current behavior; restoring partial final reports would need a separate decision.

### F08 — P1 · Incorrect documentation · Startup suggestions raise after partial failures

**Claim:** [suggested_startups/SKILL.md](../../skills/suggested_startups/SKILL.md), “Output Generation”, implies that continuing after investor errors ends by returning all successful artifacts.

**Evidence:** [suggested_startups.py](../../skills/suggested_startups/suggested_startups.py) saves successful results, then raises `RuntimeError` when any investor failed. [test_suggested_startups_continues_after_investor_failure](../../tests/skill_harness/test_skill_smoke.py) explicitly checks both the raised error and the saved successful file.

**Action:** State that successful files remain but the API raises instead of returning a partial list. **Decision:** none for the documentation correction.

### F09 — P1 · Incorrect documentation · Submission failure artifacts are not returned

**Claim:** [submission_ready/SKILL.md](../../skills/submission_ready/SKILL.md), workflow step 9, says a generated failure report is appended to the returned list.

**Evidence:** [submission_ready.py](../../skills/submission_ready/submission_ready.py), `submission_ready`, saves a failure report and raises on discovery or per-startup failures. It returns the flattened artifact list only on the success path. [Submission tests](../../tests/skills/test_submission_ready.py) include discovery failure and saved failure-report behavior.

**Action:** Document success return, persisted partial output and raised failure as distinct outcomes. **Decision:** none for describing the current contract.

### F10 — P1 · Incorrect documentation · Potential-investor recomputation guarantee

**Claim:** [potential_investors/SKILL.md](../../skills/potential_investors/SKILL.md) says rankings are recomputed on every explicit invocation and do not use dataset-revision freshness.

**Evidence:** [potential_investors.py](../../skills/potential_investors/potential_investors.py) calls `find(selection="reusable")` and can return before requesting `startup_profile`. The cache includes startup/community source datasets. [expert_search.py](../../skills/expert_search/expert_search.py) has the same early return.

**Action:** Correct the documentation to describe the retained behavior. **Decision:** none; the user previously accepted leaving these caches as they are. This audit does not reopen that decision.

### F11 — P2 · Incorrect documentation · Expert-search source

**Claim:** [expert_search/SKILL.md](../../skills/expert_search/SKILL.md), description, identifies the `person_profile` dataset as its source.

**Evidence:** [expert_search.py](../../skills/expert_search/expert_search.py) invokes `ranking_persons(source_datasets=["sictic-members"], skill="investor_profile", ...)`. [Routing tests](../../tests/skills/test_investor_profile_ranking_routes.py) cover this integration.

**Action:** Name the stored investor-profile inputs and their prerequisite. **Decision:** none.

### F12 — P2 · Incorrect documentation · Ranking CLI flag

**Claim:** [ranking/SKILL.md](../../skills/ranking/SKILL.md) uses `--top_k 8` in its direct command.

**Evidence:** [ranking/__main__.py](../../skills/ranking/__main__.py) declares `--top-k` and `-k`.

**Action:** Correct the example; include documented command parsing in later verification. **Decision:** none.

### F13 — P2 · Internal contradiction · Bulk execution order

**Claim:** [bulk_refresh/SKILL.md](../../skills/bulk_refresh/SKILL.md), opening workflow, describes member extraction and sequential execution of a fixed skill list. Later paragraphs correctly describe concurrent jobs with prerequisites.

**Evidence:** [bulk_refresh.py](../../skills/bulk_refresh/bulk_refresh.py) selects datasets, performs pre-ingestion and runs ready registry nodes through `asyncio.gather`. [Bulk tests](../../tests/skills/test_bulk_refresh.py) cover prerequisite skips and strict cross-domain scope.

**Action:** Replace the obsolete opening workflow with a short account of the actual orchestration; reference the registry for the skill list. **Decision:** none.

### F14 — P2 · Incorrect documentation · Dataset-chat infrastructure and setup

**Claim:** [dataset_chat/SKILL.md](../../skills/dataset_chat/SKILL.md) requires Docling-Serve and Rclone RC hosts and describes Ollama as the embedding backend.

**Evidence:** [Docling conversion](../../lib/infrastructure/document_conversion/docling_stack/docling.py) constructs the in-process converter; [storage](../../lib/storage.py) is local; [model_config](../../lib/model_config.py) resolves configurable model endpoints. The searched runtime code does not consume `DOCLING_HOST` or `RCLONE_HOST`.

**Action:** Replace the obsolete stack diagram and mandatory environment list with links to shared infrastructure/setup ownership. Retain the useful warning that retrieval can synchronize and write. **Decision:** none.

### F15 — P2 · Incorrect documentation · LLM-chat ownership and credentials

**Claim:** [llm_chat/SKILL.md](../../skills/llm_chat/SKILL.md) says harness commands call this skill internally and lists a Gemini key among required `.env` definitions.

**Evidence:** [llm_chat/__main__.py](../../skills/llm_chat/__main__.py) is a CLI wrapper around shared `generate_markdown`; no runtime imports of a skill-level llm_chat API were found. Other workflows use the shared generation APIs. [model_config](../../lib/model_config.py) resolves credentials by endpoint, and `install.sh` explicitly allows an unused Gemini key to be blank.

**Action:** Describe the operational wrapper and link to provider-specific setup. Do not invent a new facade to make the current wording true. **Decision:** none.

### F16 — P1 · Missing operational documentation · Dataset deletion scope

**Claim/gap:** [dataset_maintenance/SKILL.md](../../skills/dataset_maintenance/SKILL.md) supplies delete examples without explaining their differing effects.

**Evidence:** [maintenance.py](../../skills/dataset_maintenance/maintenance.py), `delete_dataset_index`, has three paths: dataset only removes that tenant across shared model collections **and deletes its parsed directory**; dataset plus embeddings removes one tenant/model and resets matching index metadata; embeddings only deletes the whole shared model collection and resets affected manifests. Raw source data is not deleted by these paths.

**Action:** Add a compact operation/effect/default table before destructive examples. **Decision:** none for documentation; no deletion was run during this audit.

### F17 — P1 · Unsupported guarantee · Rebuild “never re-parses”

**Claim:** [dataset_maintenance/SKILL.md](../../skills/dataset_maintenance/SKILL.md) guarantees rebuild never re-parses.

**Evidence:** `rebuild_dataset_index` preserves parsing checkpoints, as covered by [rebuild tests](../../tests/dataset_maintenance/test_rebuild_index.py). However, its [CLI](../../skills/dataset_maintenance/__main__.py) runs normal `sync_datasets` by default. [reconcile_conversions](../../lib/datasets/conversion.py) can reparse changed sources, parser versions or missing/stale parsed output.

**Action:** Say the reset preserves valid parsed output; the subsequent normal sync may convert stale content. The existing unit test covers the reset, not an unconditional end-to-end guarantee. **Decision:** none for narrowing the claim.

### F18 — P2 · Stale/missing coverage · Shared library map

**Claim:** [architecture.md](../../skills/standards_and_architecture/references/architecture.md), “Small Utilities”, lists `lib.json_parser`, which is absent. The map omits `lib.batch_audit` and `lib.markdown_tables`.

**Evidence:** The full AST inventory confirms module presence. [batch_audit](../../lib/batch_audit/engine.py) owns shared checklist execution, canonical JSON, cache validation and technical-error recording; its [schema](../../lib/batch_audit/schema.py) and [rendering](../../lib/batch_audit/rendering.py) APIs are used by multiple skills. [markdown_tables](../../lib/markdown_tables.py) owns shared table parsing.

**Action:** Correct the map. Add only the cross-skill audit contract to standards: shared execution/validation/rendering, distinguish missing evidence from technical errors, and let the owning skill decide whether errors block its final output. Do not enumerate every private helper. **Decision:** none for mapping; review the exact new contract text in its category iteration.

### F19 — P2 · Contradiction/overgeneralization · One package template does not fit all skill types

**Claim:** [standards](../../skills/standards_and_architecture/SKILL.md), “Public APIs and structure”, and [architecture reference](../../skills/standards_and_architecture/references/architecture.md) require a facade named after every skill and a `__main__.py`, while standards also recognizes instruction-only skills.

**Evidence:** `standards_and_architecture` has no CLI, `llm_chat` is a CLI wrapper, maintenance skills expose operations, and ranking has established shared APIs. [Contract coverage](../../tests/skill_harness/cases.py) explicitly classifies standards as docs-only.

**Action:** Qualify the executable-skill template and document narrow templates for instruction-only and operational/shared skills. **Decision:** none to recognize established types; no new entry points or relocations are proposed.

### F20 — P2 · Ambiguous scope · External synchronization versus explicit imports

**Claim:** [architecture reference](../../skills/standards_and_architecture/references/architecture.md), storage section, says optional external synchronization must not be called from skill code. [standards](../../skills/standards_and_architecture/SKILL.md), ingestion section, prohibits introducing it implicitly.

**Evidence:** [ensure_startup_dataset](../../lib/startups/sources.py) can perform a configured, gated Dealum refresh and is routinely called by skills. Explicit [Dealum import](../../skills/dealum_import/dealum_import.py) and [website import](../../skills/startup_website_import/startup_website_import.py) are existing workflows.

**Action:** Define whether “external synchronization” means application-storage mirroring, and distinguish it from existing source imports. Record the existing Dealum side effect without prohibiting legitimate import skills by accident. **Decision:** clarify wording/scope; do not disable imports.

## Findings: ownership, structure and verification

### F21 — P3 · Duplication · Person and insight contracts are repeated

**Evidence:** Canonical filenames/identifier priority appear in [standards](../../skills/standards_and_architecture/SKILL.md), [person_profile](../../skills/person_profile/SKILL.md) and [team_profile_revised](../../skills/team_profile_revised/SKILL.md). Insight construction, save/return and CLI rules recur in traction, DD and matching skills. The standards People table also restates individual skill responsibilities.

**Action:** Keep the full rule in standards; individual skills retain only relevant consequences, prerequisites and a link. Keep the People table as an index if useful, without expanding it into another workflow description. **Decision:** presentation review only; preserve the meaning while removing duplication.

### F22 — P3 · Structural inconsistency · No stable document template

**Evidence:** The inventory finds one skill without a Markdown heading and six without a literal `## Usage` heading; standards appropriately need not have a usage command. Documents mix procedure scripts, frameworks, setup guides and short CLI lists. [startup_profile/SKILL.md](../../skills/startup_profile/SKILL.md) repeats framework wording from [query.md](../../config/startup_profile/query.md), while some other skill files barely document input/output behavior.

**Action:** Use a small template by skill type. Keep runtime prompt wording in `config/`; a short skill-specific output description is useful and need not be deleted merely because it overlaps. Apply the pilot template before mass normalization. **Decision:** agree template in the pilot; do not rewrite every skill now.

### F23 — P3 · Misplaced/stale instructions · Dated maintenance reminders

**Evidence:** [bulk_refresh](../../skills/bulk_refresh/SKILL.md) and [potential_investors](../../skills/potential_investors/SKILL.md) contain reminders instructing agents to flag maintenance after 1 June 2026. The latter describes local-versus-cloud ranking strategies while [ranking_top_k](../../skills/ranking/ranking_top_k.py) implements the shared Swiss tournament. DD instructions also speak of a background script without documenting how execution is actually launched.

**Action:** Move outstanding maintenance work to the backlog, remove expired runtime reminders and describe actual execution surfaces. Keep working procedure in `AGENTS.md`. **Decision:** none; these text instructions were audited, not executed as user requests.

### F24 — P2 · Known implementation discrepancy · Infrastructure error typing

**Evidence:** [standards](../../skills/standards_and_architecture/SKILL.md), “Logging and errors”, requires structured `InfrastructureError`; its known-discrepancy section correctly acknowledges exceptions. [ApifyAdapter](../../lib/infrastructure/apify.py) wraps failures as `RuntimeError`, while [DealumAdapter](../../lib/infrastructure/dealum.py) can expose HTTP/provider exceptions.

**Action:** Keep the normative rule and an explicit, bounded exception record until a separate adapter review resolves it. Do not claim all callers receive structured metadata. **Decision:** separate code work; already known, not a newly discovered regression.

### F25 — P2 · Known implementation discrepancy · Docling model calls bypass LiteLLM

**Evidence:** [standards](../../skills/standards_and_architecture/SKILL.md) already records this exception. [build_converter](../../lib/infrastructure/document_conversion/docling_stack/docling.py) configures `PictureDescriptionApiOptions` with a direct chat-completions URL and an inline picture prompt.

**Action:** Preserve the discrepancy record for infrastructure review, including prompt ownership. Do not normalize standards to permit arbitrary new provider calls. **Decision:** separate implementation review; not a new discovery.

### F26 — P2 · Verification gap · Tests do not check document claims

**Evidence:** [skill contract tests](../../tests/skill_harness/test_skill_contracts.py) check imports, available CLI help, coverage classification, dependency keys and listed return annotations. They do not parse documented commands, compare documented parameters, check document links or prove all narrative guarantees. The stale `--top_k` example survives these tests. CLI-help checks are also duplicated in the [CLI contract suite](../../tests/cli/test_entrypoint_contract.py).

**Action:** Later add inexpensive checks for link targets, frontmatter/name agreement, registered dependency cycles and parsing representative documented commands with execution mocked. Consolidate duplicated generic help checks while retaining substantive argument/error tests. Keep behavior/side-effect review human-readable; do not treat a heading linter as semantic verification. **Decision:** test-only follow-up after the pilot establishes the document structure.

## Findings requiring deliberate contract review

### F27 — P1 · Existing behavior not fully documented · Explicit people outside the roster

**Claim:** [standards](../../skills/standards_and_architecture/SKILL.md) calls the manual roster authoritative; [person_profile/SKILL.md](../../skills/person_profile/SKILL.md) describes profiling roster people.

**Evidence:** [person_profile.py](../../skills/person_profile/person_profile.py), `_person_profile_result`, adds an explicitly requested, unmatched name as a sparse `Person`. The roster is still required and is not edited. Git history traces the sparse-person behavior to `387f70d`, predating the recent standardization.

**Action:** Clarify whether authority governs automatic selection only or forbids explicit out-of-roster requests as well. Document the retained behavior unless a change is separately approved. **Decision:** yes; do not remove the explicit-name path as a documentation cleanup.

### F28 — P1 · Existing naming conflict · Startup-suggestion artifact identity

**Claim:** [standards](../../skills/standards_and_architecture/SKILL.md), identity section, says display names are not artifact identity and established identifiers must be preserved.

**Evidence:** [suggested_startups.py](../../skills/suggested_startups/suggested_startups.py), `_prepare_outputs`, uses `identifier=person.display_name` even though stored investor profiles are looked up by LinkedIn ID. The behavior appears in history at `e9c20ee`, and the partial-failure test expects the name-based suggestion filename. This is a separate artifact convention from person-profile filenames.

**Action:** Decide whether to document an established suggestion-output exception or separately plan a migration after inspecting consumers/history. **Decision:** yes; no filenames should change in the standards/documentation iteration.

### F29 — P1 · Freshness coverage gap · Original team profile does not track supplied profile content

**Claim:** [standards](../../skills/standards_and_architecture/SKILL.md), “Selection and freshness”, requires effective dependency content to participate in reuse where it affects the result.

**Evidence:** [team_profile.py](../../skills/team_profile/team_profile.py) builds its key from its own prompts and queries and returns a reusable team artifact before calling person profiling. An edit to a person-profile insight alone need not change an indexed source revision. [team_profile_revised.py](../../skills/team_profile_revised/team_profile_revised.py) instead materializes profiles and includes their actual shared context in its key.

**Action:** Record the older workflow's limitation. Any cache change belongs to an explicitly scoped review of `team_profile`, with regression coverage for an edited dependency. **Decision:** yes; do not change the older skill while piloting People documentation or remove either team skill without approval.

### F30 — P2 · Stale current reference · Founder traits described as optional

**Claim:** [checklist_decisions.md](../../skills/team_profile_revised/references/checklist_decisions.md), consolidation, calls N001's source an “optional person-profile founder section”. Its opening also broadly describes data-room-only retrieval.

**Evidence:** [person_profile.py](../../skills/person_profile/person_profile.py), `_generate_single_profile`, always adds configured founder-trait instructions. [team_profile_revised/SKILL.md](../../skills/team_profile_revised/SKILL.md) correctly states that normal person-profile dependencies include LinkedIn enrichment; only active founders receive the trait assessment.

**Action:** Update this current decision reference to distinguish conditional applicability to founders from an optional generation mode, and distinguish team-audit retrieval from dependency enrichment. Preserve the three original registers as historical source material. **Decision:** none; the user already settled this behavior.

## Proposed ownership and structure

| Document | Owns | Avoid |
|---|---|---|
| `AGENTS.md` | Scope, approval, compatibility investigation and verification procedure | Library APIs, model configuration and per-skill workflow rules |
| Standards skill | Shared technical contracts and named ownership boundaries | Full skill procedures, exhaustive helper lists and dated reminders |
| Per-skill `SKILL.md` | Purpose, actual public surface, prerequisites, outputs, side effects and failure/reuse behavior | Reimplementing shared rules or reproducing entire runtime prompts |
| `config/` | Runtime prompts, schemas, checklists and settings | Becoming a second place for contributor procedures |
| References | Module/layout maps, longer examples and explicitly marked historical decisions | Competing current contracts |
| Tests | Executable compatibility evidence | Being treated as unconditional proof that documentation is correct |

For an executable insight skill, pilot this structure:

```text
Frontmatter: name and concise description/trigger
# Purpose
## Inputs and outputs
## Workflow and dependencies
## Side effects and failure behavior
## Usage
## References
```

Describe existing-artifact selection and refresh behavior under workflow/side effects; explicitly distinguish missing inputs, valid empty input, missing evidence, technical failure and partial persistence where they differ. State direct-call prerequisites separately from registry scheduling. Distinguish Python arguments from CLI options. Link to the canonical function instead of duplicating its entire signature when a short explanation suffices.

For operational skills, use **Purpose / Operations and effects / Usage / References**, including destructive scope and dry-run defaults. For instruction-only standards, retain the category-based technical contract structure and entry links. Uniformity should make the same kind of information easy to find; it should not create extra APIs or compulsory empty sections.

## Iterations and completion criteria

1. **People pilot:** reconcile F01–F04, F27 and F30; propose concise wording for roster discovery, read-only readers, profiling and consumers. Separate unresolved manual-output/explicit-name decisions from straightforward documentation corrections. Verify that LinkedIn → email → full-name identity, manual precedence, explicit discovery and standard founder enrichment remain unchanged.
2. **Insights and datasets:** review F05, F10, F16–F18, F28 and F29; distinguish documentation corrections from cache, filename and deletion behavior changes. Keep previously accepted limitations explicit.
3. **Infrastructure:** resolve wording/ownership for F14, F15, F20, F24 and F25; review the remaining library APIs against the inventory, including bootstrap and test-injection exceptions to dependency-instantiation guidance.
4. **Skills and orchestration:** align remaining per-skill APIs, failure outcomes and usage; cover F06–F13, F19 and F21–F23. Inventory additional public-looking helpers without creating facades just for symmetry.
5. **Repository-wide closeout:** add the agreed document checks, sweep remaining guides/references/configuration, remove redundant rules, and review the complete diff. Every register item should be fixed, explicitly accepted, or deferred with an owner/scope. Every skill should have an appropriate template and a verified public contract.

Each iteration should produce proposed text, exact supporting code/test evidence, a short list of contract decisions and then a bounded diff. Do not combine documentation normalization with unrelated refactors. The existing `AGENTS.md` already owns approval procedure; it does not need a second copy here.

## Verification performed and limits

- Static inventory: all 27 skill frontmatter names match their directories, and the skill package names match `SKILL_COVERAGE`; all 14 registered bulk entries have resolvable dependencies and the current graph is acyclic.
- Markdown path scan: no missing relative file targets in the audited skill documents, root instructions and skill references. This checks file existence, not section anchors, bare code-formatted paths or semantic correctness; it therefore does not catch the absent `lib.json_parser` mention.
- **110 tests passed** across skill contracts, CLI contracts, standard person profiles, bulk refresh, DD/batch integration, local skill smoke and index-reset behavior. Services and storage were mocked/isolated by existing fixtures. No production workflow, provider call or destructive maintenance command was requested.
- No claim of full semantic verification of all 92 library modules, every runtime prompt, all repository documentation, concurrency races or live external services. Those remain category work, not reasons to silently expand this iteration.

Test command:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /Users/openclaw/miniconda3/envs/sictic-env/bin/python -m pytest -p pytest_mock -q \
  tests/skill_harness/test_skill_contracts.py \
  tests/cli/test_entrypoint_contract.py \
  tests/person_profile/test_person_profile_standard.py \
  tests/skills/test_bulk_refresh.py \
  tests/skills/test_dd_checks_and_batch_audit.py \
  tests/skill_harness/test_skill_smoke.py \
  tests/dataset_maintenance/test_rebuild_index.py
```

The pre-existing `.gitignore`, standards and root-instruction changes were preserved. This audit adds only this register and its companion inventory; neither has been committed.
