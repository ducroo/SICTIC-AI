# Batch-audit workflows audit — 6 September 2026

Current status: see the [documentation closeout](documentation-closeout-2026-09-06.md). The observations and proposals below retain their historical audit context.

The original audit changed no implementation, configuration, checklist or existing instruction document. Authorized follow-up changes are recorded below.

Follow-up implementation: after the audit, the user authorized changes for
B01–B03 and accepted the prompt-based boundary in B04. The findings below retain
the original audit snapshot. `batch_audit` now assesses supplied context even
when search has no hits, without a caller-level switch. Its underlying
`dataset_chat_json` call opts into the existing shared-context behavior;
ordinary dataset-chat callers and technical retrieval errors are unchanged.
SHA resolves only the LLM-selected candidate, retaining the configured acceptance
threshold. DD now has a 14-item `7_product_general` fallback; specialist variants
still take priority. B04 requires no change. No one-off cache invalidation or
output-version bump was performed. Other audit findings remain open.

Follow-up verification: **64 focused tests passed**, including ten new cases.
Before implementation, six new cases reproduced the reported failures and four
confirmed existing correct behavior. Tests cover zero-hit assessment with and
without shared evidence, full-document SHA assessment, authoritative SHA selection
and resolution failure, and general/specialist DD product selection. No live
workflow or model-quality assessment was run.

The proposed standards text and comparison below describe the pre-fix snapshot;
the proposed `allow_empty_retrieval` caller instruction is superseded by the
user's decision to make zero-hit assessment standard for every batch audit.

Scope: `lib.batch_audit`, `dd_checks`, `team_profile_revised`, `submission_ready`, `sha_review`; their skill documents, configuration, registry entries, relevant retrieval/Insight/generation contracts and focused tests. This follows the [documentation consistency audit](/Users/openclaw/SICTIC-AI/docs/reviews/documentation-consistency-audit-2026-09-06.md) and the People documentation pilot.

The snapshot is local `main` at `1be1a27`, including the existing uncommitted documentation work. Findings describe current behavior, not necessarily regressions from that work. Code and tests establish behavior; they do not automatically establish the intended contract. This report is evidence for the next iteration, not another instruction source.

## Main conclusion

The shared audit engine is the right common entry point, and all four consumers use it. They consistently block final output when returned checks contain technical errors. Most differences in statuses, dependencies and final artifacts serve different purposes and should remain.

The most consequential gaps are SHA assessment being skipped despite supplied full documents, SHA path resolution changing the selected agreement, silent omission of DD product checks, and submission evidence restrictions relying solely on the prompt. These need explicit implementation decisions before documentation can describe stronger guarantees.

## Workflow comparison

| Contract | `dd_checks` | `team_profile_revised` | `sha_review` | `submission_ready` |
|---|---|---|---|---|
| Selection | Classifies industry, selects chapter variants | Same four categories at every stage | Identifies SHA, loads complete parsed text, ranks all configured reference templates | Named submissions or all Application / Under review candidates; processes startups sequentially |
| Checklist size | 73 common checks + 12 biology, 20 hardware or 19 software checks; general classification runs only 73 | 40 checks: 14 / 10 / 10 / 6 by category; 12 marked `(core)` | 107 checks across five checklists | 37 checks in seven sections |
| Shared evidence prefix | Common audit instructions; no supplied profile | Actual startup and standard person profiles plus team instructions | Complete selected SHA and reference SHA plus SHA instructions | Policy and submission instructions; no complete submission document supplied as shared evidence |
| Retrieval | Startup dataset per check | Startup dataset per check | Startup dataset per check, intended as supplemental evidence | Startup dataset per check; Dealum-only restriction is in the prompt |
| Successful retrieval with zero chunks | Static `Not Found` | May assess using shared profiles (`allow_empty_retrieval=True`) | Static `unclear`, despite supplied full documents | Static `Unclear` |
| Status scale | Not Found / Critical / Borderline / Sufficient / Fine | Assessed / Insufficient information / Not applicable | unclear / too weak / balanced / too strong | Pass / Fail / Unclear |
| Final processing | Deterministic common Markdown tables; no synthesis LLM | Concise category synthesis; core weighting and grouped evidence gaps | Material-finding synthesis with mechanical document-selection header | Deterministic checklist table plus schema-validated proposed action constrained by stage |
| Successful public return | One final Markdown Insight | One final Markdown Insight | One final Markdown Insight | Checklist then response Insight for each successful startup |
| Failure behavior | Waits for chapter outcomes; any failure blocks final report | Dependency/audit failures block synthesis | Identification/ranking/audit failures block final report | Continues other candidates, saves failure report, then raises if any failed; successful files can already exist |
| Bulk dependencies | `startup-profile`; direct DD does not call or consume it | `startup-profile`, `person-profile`; direct workflow also requests normal profiles | None | None |

Canonical JSON audits remain internal in all four public skill results. `batch_audit` is a library API returning one `InsightFile`, not another public skill variant.

### Cache and side-effect differences to preserve

- All four workflows prepare and synchronize their dataset before audit/final cache lookup. `batch_audit` itself checks its cache before any search; a reusable hit does not synchronize. `dataset_search` synchronizes when actually invoked.
- Audit freshness includes indexed dataset revisions and the effective checklist, instructions/shared context, status configuration, shared schemas and structured-output configuration. Any technical error makes the whole checklist artifact ineligible for automatic reuse. Successful checks inside that failed checklist are rerun; other successful checklist artifacts can be reused.
- DD reruns industry selection and assembles its final table each invocation; it reuses individual checklist audits. Team refreshes its standard profile dependencies before final-cache lookup and includes their actual content. SHA checks its final cache before identification, ranking and audits.
- Submission obtains the current audit before evaluating timestamped output reuse. The response key includes stage and audit content. Its timestamped lookup uses exact-model `is_reusable`, unlike manual-first/ranked-model `find`. Do not silently standardize these into one selection policy.
- Stage-only reuse has supporting implementation: Dealum rendering excludes `step`, and `application.raw.json` / `manifest.json` are excluded from indexing. Reuse still depends on unchanged indexed dataset content and configuration, not only unchanged Dealum content. Unrelated startup dataset changes can invalidate submission results.
- Preparing a startup can import Dealum data. Normal team profile dependencies can enrich LinkedIn and save profiles. Submission imports Dealum and saves outputs; it sends no messages and changes no Dealum stage. An evidence restriction does not imply read-only execution.

## Findings and decisions

Priorities indicate review order. P1 can change assessment or coverage; P2 concerns contract reliability, diagnostics or instructions. No finding below has been fixed in this audit.

### B01 — P1 · SHA can ignore the full agreement when retrieval has no hits

[SHA `_run_audits`](/Users/openclaw/SICTIC-AI/skills/sha_review/sha_review.py:275) supplies full SHA/reference text but leaves `allow_empty_retrieval=False`. [Dataset chat](/Users/openclaw/SICTIC-AI/skills/dataset_chat/dataset_chat.py:130) returns `None` on zero chunks before generation. The engine then records generic missing evidence, without assessing the provided agreement. This conflicts with the [SHA evidence hierarchy](/Users/openclaw/SICTIC-AI/config/sha_review/audit_instructions.md), where semantic search is supplemental.

**Verified:** with full clause evidence and an empty successful search, the real check runner made no model call and returned `unclear`. Enabling the existing shared-evidence option reached the mocked generator. Technical retrieval failures remain separate.

**Recommendation:** use the existing option for SHA and add regression coverage at the SHA-to-engine boundary. This is a scoped caller correction, not a new generation mode. Preserve errors as errors.

### B02 — P1 · SHA filename similarity can replace the substantive selection

[`_identify_sha`](/Users/openclaw/SICTIC-AI/skills/sha_review/sha_review.py:104) resolves the selected path and alternatives, then chooses the highest path-match score across them. It retains the original identification metadata. Filename similarity therefore outranks the model's substantive choice, although the [selection prompt](/Users/openclaw/SICTIC-AI/config/sha_review/document_identification_prompt.md) prefers the latest substantive agreement.

**Verified:** a primary agreement resolving at 92 and an older alternative resolving at 100 selected the alternative, while retaining the primary path and concerns in identification metadata. The final report can consequently assess one document and describe selection caveats for another.

**Recommendation:** preserve substantive candidate order when resolving paths; if an alternative must be selected, reassess or explicitly reconcile its selection metadata. The fallback policy needs agreement before implementation. The existing SHA test covers a misspelled primary path, not competing candidates.

### B03 — P1 · DD silently omits product review for general/unknown industry

[`chapter_by_chapter`](/Users/openclaw/SICTIC-AI/skills/dd_checks/dd_checks.py:139) skips a chapter when neither the industry variant nor a general fallback exists. Configuration has three product variants but no `7_product_general`. Missing classification evidence falls back to `general`.

**Verified:** actual configuration selected six checklists and 73 checks for `general`, omitting product altogether. The final report can still be produced successfully, despite the documentation describing comprehensive coverage.

**Decision:** choose a general product checklist, require a classification decision, or explicitly report the omitted coverage. Do not silently invent product questions or change industry classification.

### B04 — P1 · Dealum-only evidence is a prompt restriction, not a retrieval boundary

[Submission processing](/Users/openclaw/SICTIC-AI/skills/submission_ready/submission_ready.py:452) passes the entire startup dataset to the engine. [`dataset_search`](/Users/openclaw/SICTIC-AI/lib/datasets/search.py:63) has no source-subdirectory filter. Website, LinkedIn or other data-room chunks can therefore be supplied, with the [prompt](/Users/openclaw/SICTIC-AI/config/submission_ready/llm_instructions.md) asking the model to disregard them.

**Risk:** excluded documents can displace allowed evidence in retrieval or be used despite the instruction. No live evidence contamination was demonstrated; the confirmed finding is the absence of an enforced boundary. The audit reviewer validates response fields, not citation provenance.

**Recommendation:** agree a shared retrieval source constraint before implementing this requirement. Avoid creating a submission-specific search implementation or another skill entry point. Narrowing retrieval would also require reviewing freshness semantics; current freshness covers the whole startup dataset.

### B05 — P2 · Cached/manual JSON validation does not establish checklist coverage

[`validate_audit_document`](/Users/openclaw/SICTIC-AI/lib/batch_audit/schema.py:18) checks common structure and statuses. It does not compare owner, dataset, chapters, check identities or counts with the requested checklist, or reject duplicate check numbers. [Cache reuse](/Users/openclaw/SICTIC-AI/lib/batch_audit/engine.py:260) relies on that validation. Automatic generation constructs all requested checks; manual overrides bypass configuration freshness by established design.

**Verified:** a manual audit containing one of two requested checks and a different dataset/owner was accepted and reused without generation.

**Decision:** distinguish manual authority over answers from structural compatibility with a checklist. If compatibility is required, validate expected coverage at the consumer boundary and report mismatches without overwriting or silently discarding manual work. Do not change manual precedence as an incidental fix.

### B06 — P2 · An exception without a message defeats the technical-error artifact

[`_error_result`](/Users/openclaw/SICTIC-AI/lib/batch_audit/engine.py:134) records `str(error)`. The common schema requires a nonempty error string. An exception such as `TimeoutError()` consequently creates an invalid check entry, and validation can stop the checklist before its diagnostic JSON is saved.

**Verified:** the real check runner produced `error=""`; common validation rejected it. This does not become a successful assessment, but loses the intended persisted diagnostic result.

**Recommendation:** retain a nonempty exception description, with type fallback, inside the existing error contract. Add a focused regression test when fixing it.

### B07 — P2 · Two skill documents promise the wrong failure result

- [DD documentation](/Users/openclaw/SICTIC-AI/skills/dd_checks/SKILL.md) promises chapter errors inside a partial final Markdown report. [Code](/Users/openclaw/SICTIC-AI/skills/dd_checks/dd_checks.py:205) raises before final report creation. Its configuration-key example also omits structured-output configuration, and local JSON-repair wording duplicates/outdates the shared generation responsibility.
- [Submission documentation](/Users/openclaw/SICTIC-AI/skills/submission_ready/SKILL.md) promises a failure report appended to the return list. [Code](/Users/openclaw/SICTIC-AI/skills/submission_ready/submission_ready.py:727) saves the report and raises. “Not retrievable” should distinguish a successful search with no evidence from a technical retrieval failure.

**Recommendation:** document the existing stop/raise behavior and saved intermediate artifacts; do not change execution to satisfy stale prose. These confirm F07 and F09 in the initial audit.

### B08 — P2 · Submission retry behavior conflicts with the shared standard

[`_retry`](/Users/openclaw/SICTIC-AI/skills/submission_ready/submission_ready.py:81) immediately retries every exception three times for application discovery, import and synchronization. This includes permanent configuration/validation failures, contrary to the [shared retry rules](/Users/openclaw/SICTIC-AI/skills/standards_and_architecture/SKILL.md:335). It does not wrap every candidate step, yet the outer handler labels all candidate failures “failed after three attempts.”

Separately, [`_latest_existing_artifacts`](/Users/openclaw/SICTIC-AI/skills/submission_ready/submission_ready.py:599) can label existing, unchecked or partially saved files as an “Older usable result.” It does not establish freshness or a complete previous run.

**Recommendation:** classify retryable failures at their existing service boundary and make diagnostics describe actual attempts and artifact status. This is not grounds for removing established provider retries or adding another generic wrapper.

### B09 — P2 · Editing an internal audit does not necessarily refresh its synthesis

Team and SHA return a reusable final result before reading internal audit artifacts. Their final keys cover source revisions/configuration (and actual shared profiles for team), but not current audit JSON contents. An edited audit alone therefore need not invalidate the final synthesis. Submission includes audit content in its downstream keys; DD rebuilds final tables.

Evidence: [team final cache](/Users/openclaw/SICTIC-AI/skills/team_profile_revised/team_profile_revised.py:111), [SHA final cache](/Users/openclaw/SICTIC-AI/skills/sha_review/sha_review.py:388), [submission keys](/Users/openclaw/SICTIC-AI/skills/submission_ready/submission_ready.py:480).

**Decision:** are internal audits supported human-editing inputs, or implementation artifacts? If editing is supported, define downstream invalidation explicitly. Current shared Insight standards already say that editing an Insight does not automatically invalidate its consumers; do not claim automatic propagation in skill documentation.

### B10 — P2 · Prompt composition and enforcement need clearer ownership

- Explicit `llm_instructions` **replace** common audit instructions; the engine does not append them. All callers still use the common response schema. SHA documentation's claim that shared instructions come from `config/batch_audit/` obscures this distinction. A common-instruction edit changes freshness but does not add that text to custom callers' prompts.
- The per-check prompt and retrieval query contain the description; the title and chapter are not included. Titles, original IDs and `(core)` markers are preserved in canonical JSON for synthesis. The current team descriptions repeat their original IDs. **The core markers do reach the team synthesis**; their absence from per-check prompts is not evidence that synthesis ignores them.
- Team's audit prompt says no LinkedIn retrieval occurs “by this workflow,” while its normal profile dependencies can perform enrichment. Its SKILL now explains this correctly. The prompt should eventually distinguish the audit step from dependency preparation.
- Team/SHA synthesis requirements concerning citations, length, grouped gaps and materiality are primarily prompt rules. Shared Markdown generation rejects empty output, but does not validate those semantic requirements. Passing pipeline tests does not establish synthesis quality.

Evidence: [engine instruction/default and prompt construction](/Users/openclaw/SICTIC-AI/lib/batch_audit/engine.py:92), [team prompt](/Users/openclaw/SICTIC-AI/config/team_profile_revised/audit_instructions.md), [team synthesis configuration](/Users/openclaw/SICTIC-AI/config/team_profile_revised/summary_instructions.md), [shared Markdown generation](/Users/openclaw/SICTIC-AI/lib/infrastructure/ai_text_generation/generation.py:81).

**Recommendation:** document composition once, keep check descriptions self-contained, and retain domain-specific synthesis rules in configuration. Evaluate synthesis quality against representative audit fixtures rather than adding an expanding list of mandatory topics to the shared engine. No new failure threshold or synthesis reviewer is proposed without a separate decision.

## Shared-library coverage and document ownership

All four implementation modules were read, including their internal helpers. These are the contracts worth naming; documenting every private helper would duplicate implementation details.

| Module/API | Contract to retain in documentation |
|---|---|
| `checklist.parse_checklist`; `Checklist`, `ChecklistChapter`, `ChecklistCheck` | One H1, H2 chapters, H3 checks with nonempty descriptions; optional terminal `**Keywords:**` block. Generated numbers are positional, optionally prefixed by the H1 number. Heading IDs remain text. H4+ and introductory prose outside checks are rejected. |
| `engine.batch_audit` | Single shared asynchronous audit API; caller-owned instructions/statuses; independent concurrent checks, returned in checklist order; one canonical JSON Insight. |
| Engine response/prompt helpers | Shared schema specialization and business reviewer, description-based retrieval, explicit shared-evidence option, missing-evidence/error distinction. Leave helper signatures out of standards. |
| `schema.validate_audit_document`, `schema.audit_errors` | Common structural validation plus explicit technical-failure inspection. Current validation does not establish expected coverage or citation truth. |
| `rendering.json_to_markdown_table` | Deterministic common table. It can render error entries; final-output gating is the caller's responsibility. |
| Existing Insight/generation/retrieval services | Own artifact paths, freshness, model validation/recovery and synchronization. Link to their shared standards instead of repeating them in each skill. |

The engine uses `InsightFile(skill="batch_audit", identifier=f"{owner}-{checklist.title}", subdir=True, extension="json")`. The title participates in artifact identity; checklist content participates in freshness. Preserve that established naming convention. A common module does not need a competing public `batch_audit` skill.

### Proposed shared standards text

Proposal only, for a short “Checklist audits” subsection under Skills and orchestration:

> Use `lib.batch_audit.batch_audit` for structured checklist assessment. Keep domain questions, status meanings, evidence restrictions and synthesis rules in the owning skill's configuration.
>
> Parse checklists with `parse_checklist`: one H1 title, H2 chapters and H3 checks with self-contained descriptions; optional `**Keywords:**` follows the description. Generated numbers are positional. Titles and original identifiers remain in the audit JSON; only descriptions drive the per-check prompt.
>
> Supplied `llm_instructions` replace the common instructions. Enable `allow_empty_retrieval` only when the shared prefix contains documentary evidence that can support answers without additional chunks. Successful retrieval with no evidence uses the configured missing-evidence status; technical failures remain errors.
>
> Validate canonical JSON with `validate_audit_document` and inspect `audit_errors` before final output. Structural validity does not establish checklist completeness or citation accuracy. Use `json_to_markdown_table` for common tables; keep synthesis in the caller.
>
> Reuse the shared Insight and generation contracts. Audit reuse is per whole checklist, with technical-error artifacts ineligible. Synchronize before cache lookup. Each skill documents its prerequisites, final artifacts, failure behavior and additional cache inputs.

### Proposed documentation changes after decisions

| Document | Scope |
|---|---|
| `AGENTS.md` | No addition. Existing procedure and contract-preservation rules already apply. |
| Standards SKILL | Add the short shared subsection; link existing Insights, retrieval and generation sections. Do not copy domain checklists or workflow tables into it. |
| Architecture reference | Add `lib.batch_audit` and `lib.markdown_tables`; remove obsolete `lib.json_parser` entry (initial finding F18). Keep this as a module map. |
| Four workflow SKILLs | Use the People pilot structure: purpose, Inputs and outputs, Workflow and dependencies, Side effects and failure behavior, Usage, References. Retain only workflow differences and links to shared contracts/configuration. Team already largely follows it. |
| Domain configuration | Remains authoritative for assessment/synthesis criteria. Resolve B01–B04 and B10 in scoped work before documenting stronger behavior. |
| Tests | Add regression cases with approved behavioral fixes; keep documentation/link checks separate from model-quality evaluation. |

## Verification and limits

- Parsed all **19 configured checklist files**, covering **308 configured checks**, including mutually exclusive DD variants. This is syntax/count coverage, not validation of business or legal criteria.
- **54 existing focused tests passed** across batch foundations, structured engine, DD, submission, SHA, revised team and dataset chat. The test environment uses mocks and isolated storage; no live workflow, external service or operational data room was exercised.
- Separate isolated probes reproduced zero-hit shared-evidence behavior, manual audit coverage mismatch, blank exception serialization, general-industry selection and SHA alternative selection; also inspected the actual check prompt and parsed configuration inventory. These are audit observations, not newly added permanent regression tests.
- Shared Markdown generation already rejects empty output; the lack of a second local empty check in SHA is **not** a defect. Stage-only Dealum rendering/index exclusions also support the intended reuse behavior; the mocked stage-change test alone would not establish it.
- No assessment of actual Ovomind synthesis quality or legal/business correctness was performed. The configured summary limits and evidence-provenance rules are not proven by the passing tests.
- A pre-audit content-hash snapshot covers 388 existing Python, configuration, test and documentation files plus root instructions and ignore rules. Verification confirms those existing files were unchanged; this report is the only repository file added by this audit.

Recommended next iteration: resolve the four P1 findings first, then audit compatibility/error handling (B05–B06) and the supported role of edited audit artifacts (B09). Apply the small documentation corrections and uniform structure in a separate, reviewable pass. Keep submission retry changes and synthesis-quality evaluation explicitly scoped.
