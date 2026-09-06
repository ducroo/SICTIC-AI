# Ranking workflows review — 6 September 2026

Current status: see the [documentation closeout](documentation-closeout-2026-09-06.md). The observations and proposals below retain their historical audit context.

The initial audit below records behavior before the approved follow-up changes.
Scope: `expert_search`, `potential_investors`, `advocates`,
`suggested_startups`, their shared `skills/ranking` package, configuration,
CLI/harness and registry routes, and relevant shared contracts/tests.

## Approved follow-up

- **R01:** retain ranking-output caching for expert search and potential investors.
  Read the normal startup profile before checking generated-output reuse and
  include its content in the existing configuration key. Startup/community
  indexed-revision dependencies were already present and remain. Preserve manual
  ranking precedence. Investor-profile/roster edits alone remain untracked.
- **R02:** leave previously seen startup handling unchanged, as clarified by the user.
- **R03:** retain the established duplicate/missing-ID recovery.
- **R04:** restore suggestion-report filenames to canonical LinkedIn IDs.
  Pass `Person.identifier` to `InsightFile`; eligible investors already require
  LinkedIn IDs. Keep display names in report text. Existing report files are
  not migrated by this code change.
- **R05:** align public APIs, shared engine, direct CLIs and harness defaults at 16.
  Preserve existing options and list syntax.
- Normalize all five skill documents, add the short standards section, correct
  CLI help and the generated-dataset example. Include structured-output
  configuration in advocates' existing key.

Follow-up verification: **64 focused tests passed; two live tests were skipped.**
Nineteen new cases cover profile-sensitive reuse, manual ranking precedence,
the 16-result engine default, and direct/harness defaults and explicit CLI
overrides. The cache regressions failed against the original implementation.
All five skill documents have the same section structure and valid local links.
No live models, external services or operational datasets were used.

After restoring suggestion filenames, **21 relevant tests passed**, including
a new regression that verifies distinct files for people sharing a full name
and stable filenames after a name edit. That regression failed before the fix.

The remaining sections are the original audit findings and proposals, not
instructions to implement decisions that the user has deferred.

The initial review included the earlier approved documentation and batch-audit work. It follows the [initial documentation audit](/Users/openclaw/SICTIC-AI/docs/reviews/documentation-consistency-audit-2026-09-06.md). Code establishes observed behavior, not automatic authority for what the standards should prescribe. Findings below distinguish documentation corrections from decisions affecting behavior or compatibility.

## Recommended direction

The ranking algorithm is already shared by all four workflows. Preserve `skills/ranking` as its established owner. Standardize the preparation, validation, output lifecycle and documentation around that engine, while retaining the different matching objectives and public skill entry points.

Use the same document structure for all four skills and the ranking utility. Put shared API/algorithm details in `ranking/SKILL.md`, a short cross-workflow contract in standards, and domain criteria in each workflow's configuration. The most pressing behavior decisions concern cache reuse, previously seen startups, automatic repair of incomplete rankings and suggestion filenames. Do not turn those discrepancies into new standards merely by documenting current code.

## Current contracts

| Contract | Expert search | Potential investors | Advocates | Suggested startups |
|---|---|---|---|---|
| Objective | Expertise relevant to evaluating a startup | Investor fit for a startup | Ability to represent SICTIC at an event | Startup fit for each investor |
| Ranked profiles | Stored `investor_profile` from `sictic-members` | Same | Same | Stored `startup_profile` from selected startup datasets |
| Objective context | `startup_profile` requested after output-cache miss | Same | User-supplied event description | Stored investor profile, selected by canonical LinkedIn ID |
| People source | Existing manual member roster through the library reader | Same | Same | Existing manual roster in the requested community dataset |
| Shared path | `ranking_persons` → `rank_person_rows` → `ranking_top_k` → `ranking_rationale` | Same | Same | `generate_report` → the same `ranking_top_k` and `ranking_rationale` |
| Profile preparation | May import Dealum; may generate/refresh startup profile; reads member profiles without refreshing them | Same | Reads existing roster/profiles | Reads all investor/startup profiles; no profile generation, copying or indexing |
| Ranking-output reuse | Manual-first/ranked-model `find(reusable)` before reading dependencies | Same | Recomputes on every call | Recomputes on every call |
| Successful public output | One Markdown Insight in the startup | One Markdown Insight in the startup | One Markdown Insight identified by event in the community | One Markdown Insight per investor, currently identified by display name |
| Python / harness default limit | 16 | 16 | 10 | 5 |
| Direct CLI default limit | 8 | 8 | 10 | 5 |
| Bulk registry | Depends on startup-profile and investor-profile | Same | Not registered; requires event description | Community workflow depending on startup-profile and investor-profile |

All four public APIs return flat `list[InsightFile]` on success. Registry execution can prepare declared dependencies; direct calls do not automatically execute the registry. Cross-domain dependency ordering concerns the datasets selected for that bulk run; it does not discover missing prerequisite datasets automatically.

### Selection and failure policies that need explicit documentation

- The three people-ranking workflows require LinkedIn IDs to match stored profiles. Name/email-only people are omitted from automatic selection. Explicitly requested people without a matching profile cause failure; a default roster can be ranked using only the profiles available. Unknown requested candidates raise; unmatched opt-outs produce a warning and have no exclusion effect. Duplicate selected profile IDs across sources raise.
- Suggested startups also requires investor LinkedIn IDs. It resolves raw IDs or names with `Person` matching, while the people-ranking resolver also explicitly parses email references. These input parsers are not identical. Neither should be described as accepting every reference form supported elsewhere in the People library.
- Suggested startups lists startup-domain datasets when no startups are supplied, applying configured community/ignore exclusions. It does not filter that default list to active startups. Empty lists trigger default selection. Every selected startup and investor profile must exist before generation begins; one missing input aborts the whole invocation.
- During suggestion generation, investors run concurrently. Individual failures do not prevent other investors' files being saved, but **any failure ultimately raises**. Successful artifacts are not returned in a partial-success list in that case. The other three workflows propagate generation failures before saving their new result.
- Input profile selection is read-only and uses preferred stored Insights, without a freshness guarantee. Output-cache reuse and input selection are separate contracts. Generating a ranking does not verify current investor availability, interest, willingness to help or contact consent, and sends no messages.

## Decisions affecting standardization

### R01 — Ranking caches can ignore changed profile evidence

[Expert search](/Users/openclaw/SICTIC-AI/skills/expert_search/expert_search.py:34) and [potential investors](/Users/openclaw/SICTIC-AI/skills/potential_investors/potential_investors.py:35) check output freshness before requesting the startup profile or reading member profiles/roster. Their keys include their objective, shared ranking/structured-output configuration, options and indexed dataset revisions, but not actual selected profile content or the startup-profile configuration. `ensure_startup_dataset` is not an unconditional synchronization of local edits.

**Confirmed:** with valid indexed revisions, editing the manual startup profile between two invocations returned the old ranking. Startup-profile and ranking calls each occurred only once. The potential-investor test claiming “always recompute” passes because its fixture lacks indexed revisions, making cache reuse impossible.

History shows the early cache return being added in `37629bc`; advocates and suggested startups still recompute. This is a behavior/documentation conflict, not grounds to silently restore either policy.

**Recommendation:** agree one ranking-output policy. My preference is to recompute on explicit invocation while retaining stored-profile reuse. If ranking-output caching is required, read/select the actual inputs first and include profile content, roster metadata and effective settings in freshness. Uniform keys should include structured-output configuration; advocates currently omits it. Suggested-output metadata currently lists only its community dataset, not the startup inputs.

### R02 — Previously seen startups are deprioritized but not excluded

The [suggestion objective](/Users/openclaw/SICTIC-AI/config/suggested_startups/suggested_startups_prompt.md:10) declares every startup in “Interest in startups” ineligible, then instructs the model to rank them last. [Generation](/Users/openclaw/SICTIC-AI/skills/suggested_startups/generation.py:38) sends all profiles to the common ranker, which returns up to `max_startups`; there is no eligibility filter.

**Confirmed:** with one new and one previously seen startup, requesting five suggestions returned both, even with a mocked comparison that perfectly placed the seen startup last. This fails independently of whether the model follows the prompt.

**Recommendation:** resolve eligibility into canonical startup IDs before ranking, using the existing preference/track-record representations where appropriate. Permit fewer suggestions, including none, when eligibility leaves fewer candidates. Define how names in stored profile text map to startup IDs before implementing this; do not introduce a second discovery workflow or pretend sorting alone enforces exclusion.

### R03 — Ranking validation can assign positions the model never supplied

The [ranking reviewer](/Users/openclaw/SICTIC-AI/skills/ranking/ranking_top_k.py:79) removes duplicate IDs and appends missing candidates in input order. It returns no review problems, so the modified ranking is accepted rather than sent back for correction. The rationale reviewer, in contrast, rejects duplicated or missing IDs.

**Confirmed:** `['a', 'a', 'a']` for candidates `a, b, c` becomes `['a', 'b', 'c']`, with no validation problems. Membership is repaired, but the positions of `b` and `c` are not LLM judgments. Existing tests explicitly preserve this behavior, despite names suggesting retries or rejection.

**Recommendation:** treat duplicated/omitted ranking IDs as a business-validation failure and use the existing `generate_json` reviewer/correction mechanism. This changes an established recovery policy and needs approval; it is not a documentation-only cleanup. Preserve the valid LLM order and canonical IDs.

### R04 — Suggestion filenames can collide for different investors

[`_prepare_outputs`](/Users/openclaw/SICTIC-AI/skills/suggested_startups/suggested_startups.py:33) passes `person.display_name` to `InsightFile`, although investor lookup uses LinkedIn ID.

**Confirmed:** two people named Alex Smith with different LinkedIn IDs produce the same output path. Concurrent generation can overwrite one report and return two Insight objects pointing to one file. This audit tested path construction only; no operational file was overwritten.

History at `e9c20ee` and existing tests establish the name-based suggestion convention. It is a separate output type from `person_profile`; do not silently rename it under the person-profile naming rule.

**Decision:** explicitly preserve this as a documented exception with collision handling, or approve a migration to canonical IDs after reviewing consumers. This expands the earlier F28 observation with a concrete collision case.

### R05 — CLI/API defaults and option exposure differ

Expert search and potential investors default to **16** in Python, the harness and bulk refresh, but **8** through their direct Typer CLIs. Harness commands for all three people-ranking workflows do not expose the include/exclude/limit options available in Python and the direct CLIs.

Suggested startups accepts comma-separated startup names through the harness, while its direct CLI uses repeated `--startups` options. Its CLI help incorrectly describes investors as discovered from Insights; they come from the existing roster.

**Confirmed:** all eight mocked direct/harness workflow invocations succeeded; captured arguments demonstrated these differences. **Recommendation:** document the actual routes immediately; choose intended defaults and option exposure separately. Preserve public argument names and avoid adding another entry point.

### R06 — The tournament is approximate and its final comparison can exceed the batch size

[`ranking_top_k`](/Users/openclaw/SICTIC-AI/skills/ranking/ranking_top_k.py:157) shuffles candidates, compares batches of 16, advances the upper half of rank buckets and finishes with one comparison of survivors. It stops reducing when fewer than `2 * top_k` remain. The final comparison can therefore contain more than 16 profiles; results also depend on grouping.

**Confirmed limitation:** in a controlled 32-candidate example requesting 16, even perfect within-batch comparisons discarded eight members of the exact global top 16. This demonstrates an approximation, not a claim about live ranking quality or frequency.

**Recommendation:** describe the algorithm accurately and avoid claiming an exact global best-k guarantee or a universal 16-profile context cap. Keep changes to batching, recall guarantees or context budgeting as a separate decision. The dated local-versus-cloud algorithm reminder is not a description of current code: all four use this same engine.

## Documentation corrections that do not require choosing new behavior

| Document | Correction and scope |
|---|---|
| [expert_search/SKILL.md](/Users/openclaw/SICTIC-AI/skills/expert_search/SKILL.md) | Replace the obsolete `person_profile` dataset claim with stored investor-profile selection from `sictic-members`. Describe the DD-expertise objective, roster/LinkedIn eligibility, startup preparation, actual cache limitation, options and result. The current objective is narrower than the broad mentorship/investment description. |
| [potential_investors/SKILL.md](/Users/openclaw/SICTIC-AI/skills/potential_investors/SKILL.md) | Correct the “always recompute” claim to disclose actual caching until R01 is decided. Distinguish read-only investor inputs from startup preparation. Remove the dated administrative instruction and obsolete model-specific processing description. Move ranking/JSON recovery details to the shared owner. |
| [advocates/SKILL.md](/Users/openclaw/SICTIC-AI/skills/advocates/SKILL.md) | Add event inputs, existing roster/profile prerequisites, eligibility, recomputation, event-based output naming and failure behavior. Ten is a default maximum, not a guaranteed shortlist size. Preserve both existing CLI routes. |
| [suggested_startups/SKILL.md](/Users/openclaw/SICTIC-AI/skills/suggested_startups/SKILL.md) | Correct partial-failure return behavior; distinguish global input validation from per-investor generation. State display-name output naming as the existing unresolved exception. Document the configured seen-startup rule and its current enforcement gap, default dataset enumeration and direct CLI syntax. Remove repeated engine/Insight recipes. |
| [ranking/SKILL.md](/Users/openclaw/SICTIC-AI/skills/ranking/SKILL.md) | Own the shared API contracts, required LinkedIn IDs for people ranking, candidate/opt-out policies, read-only profile selection, batched approximation, current duplicate-ID handling, rationale validation and rendering. Correct the debugging option to `--top-k`; there is no `/ranking` harness command or bulk entry. |
| [standards](/Users/openclaw/SICTIC-AI/skills/standards_and_architecture/SKILL.md) | Add only a short ranking contract linking the shared skill. Reuse the existing People, Insights, generation and orchestration sections. Do not duplicate algorithm internals or domain objectives. |
| [architecture reference](/Users/openclaw/SICTIC-AI/skills/standards_and_architecture/references/architecture.md:20) | Remove the example suggesting current ranking consumes generated searchable member-profile datasets. These workflows read stored Insight text directly. Keep `skills/ranking` in its established location. |

The initial audit's F08, F10, F11, F23 and F28 are confirmed or expanded here.
The ranking CLI example is corrected in the approved follow-up.

### Uniform structure for the five SKILL documents

Use the People pilot structure:

1. **Purpose:** one sentence; the ranking objective's meaning belongs in configuration.
2. **Inputs and outputs:** real API/defaults, eligibility, artifact identity and return type.
3. **Workflow and dependencies:** preparation, stored inputs, shared ranking path and actual registry/direct-call distinction.
4. **Side effects and failure behavior:** generation versus read-only inputs, reuse, missing inputs, partial saves and raised errors.
5. **Usage:** working harness/direct examples with their actual syntax and defaults.
6. **References:** implementation, configuration and shared ranking contract.

For the ranking utility, “Inputs and outputs” documents its existing adapters rather than pretending it produces Insight files. Do not impose the public insight-producing skill template on a shared utility.

### Proposed short standards text

Proposal only; this adds no new caching, filename or recovery policy:

> Use the existing `skills.ranking` engine to compare stored profiles directly. `ranking_top_k` selects ranked IDs; `ranking_rationale` adds explanations while preserving identity and order. Use `rank_person_rows` for structured person results and `ranking_persons` for the common Markdown report.
>
> For generation, resolve people from the existing roster and select stored Insights through the shared readers. Current people-ranking workflows require LinkedIn IDs; render names and contacts from canonical people, not model output. Ranking itself does not discover people, refresh profiles, copy Insights or index them.
>
> Keep domain objectives in the owning skill's configuration. Each workflow documents eligibility, missing-input handling, prerequisite generation, ranking-output reuse, artifact identity and failures. Ranking orders the supplied candidates; it does not itself enforce domain exclusions.
>
> Reuse shared model generation, validation and Insight lifecycle APIs. See the ranking skill for batching, ID validation, recovery behavior and supported adapters. Change these contracts deliberately across their consumers.

### Code standardization after decisions

- Expert search and potential investors duplicate startup preparation, configuration, output construction, cache lookup, objective interpolation, ranking and saving. Once R01 is settled, share this orchestration internally while keeping the two established public functions and separate objectives. Advocates can reuse applicable pieces without acquiring a startup dependency.
- Reuse the same canonical people/Insight abstractions for input resolution. Before combining the two existing person resolvers, decide accepted reference forms and missing-profile policy; do not accidentally broaden or narrow either workflow's inputs.
- Keep one top-k/rationale implementation. Address R03 in that implementation, not through caller-specific ranking repair. Put suggestion eligibility in its owning workflow before the shared ranker.
- Keep model-quality rules in shared ranking/rationale configuration where they apply to all consumers, and domain criteria in each objective. JSON validation currently verifies identities and structure, not the truth of fit claims, evidence provenance or rationale quality. Do not describe those as verified guarantees.

## Verification and limits

**45 focused tests passed; two live expert tests were skipped.** Coverage included the ranking engine/adapters, all four workflow routes, suggested-startup input/generation behavior, shared skill/harness contracts and partial failure. The skipped expert test still uses a legacy directory check and an unsupported `dataset_search(return_full_docs=...)` argument, and tests semantic retrieval rather than the current stored-profile ranking route.

Isolated probes additionally verified cache behavior with indexed revisions, homonym output collisions, automatic duplicate-ID repair, ineffective seen-startup exclusion, tournament approximation, and all eight direct/harness command routes. The misleading cache/retry test names and mocks should be corrected alongside the corresponding approved fixes; passing them does not establish the named guarantees.

No live model comparison, semantic ranking-quality evaluation, operational dataset run or external request was performed. No existing file was edited. A content-hash comparison covers all **390 existing source, configuration, test and documentation files** recorded before this review; only this report was added to the repository.

Suggested next step: approve the straightforward documentation normalization, then decide R01–R04 before changing execution. R05 needs a small interface decision; R06 needs accurate documentation now and algorithm changes only if stronger ranking guarantees are required.
