# Documentation consistency closeout — 6 September 2026

This records the documentation pass and the remaining decisions. It is a review
record, not another source of working instructions. The original
[inventory](documentation-consistency-inventory-2026-09-06.md) and audit reports
remain historical snapshots.

## Coverage and ownership

All 27 skill documents now use structures appropriate to their role: 19 workflow
or shared-workflow documents, seven operational utilities, and one standards
skill. The final pass covered batch audits, startup analysis, execution tools,
imports, maintenance, member preferences and invitations. Earlier People and
ranking reviews supply the corresponding coverage for those groups.

The documents describe actual public APIs, direct CLI and harness differences,
registry dependencies, cache selection, side effects and failure behavior.
Operational utilities retain their existing interfaces; no new facade or registry
entry was introduced to satisfy a document template.

- [AGENTS.md](../../AGENTS.md) owns working procedure and scope approval.
- [Standards](../../skills/standards_and_architecture/SKILL.md) owns shared contracts.
- Individual skill documents own workflow-specific behavior and usage.
- [Architecture](../../skills/standards_and_architecture/references/architecture.md)
  maps implementation ownership and points back to those contracts.
- Configuration owns effective model instructions and schemas; documented prompt
  requirements are distinguished from mechanically enforced validation.

README and installation/operations now agree with the maintained skill documents
on invocation, storage and maintenance. The old codebase assessment is explicitly
historical. RAG assessment links are portable; external product claims were not
revalidated during this local-code review.

## Initial audit findings

See the [original findings](documentation-consistency-audit-2026-09-06.md) for
evidence. “Documented” means the prose is corrected, not that the behavior has
been approved as a new convention.

| Finding | Current status |
|---|---|
| F01 | Team discovery claim corrected in the People pilot. Stale implementation comments remain deferred. |
| F02 | Person-profile inputs and roster adapters documented. |
| F03 | LinkedIn eligibility and read-only investor source selection documented. |
| F04 | Manual investor-output overwrite conflict remains open; documentation discloses it. |
| F05 | Traction's saved missing-context response is documented. Intended missing-evidence policy remains unresolved. |
| F06 | Obsolete traction call syntax removed. |
| F07 | DD chapter failure and absence of a partial final report documented. |
| F08 | Suggested-startup partial failures and eventual exception documented. |
| F09 | Submission failure artifacts are saved before raising, not returned; corrected. |
| F10 | Ranking reuse and approved startup-profile freshness changes documented. |
| F11 | Expert-search source adapter corrected. |
| F12 | Ranking CLI examples use actual options. |
| F13 | Bulk preparation, concurrent ready tasks and failure propagation documented. |
| F14 | Dataset-chat infrastructure, API and evidence behavior corrected. |
| F15 | LLM-chat shared implementation and provider configuration corrected. |
| F16 | Dataset/model deletion scopes and retained artifacts documented. |
| F17 | Unsupported no-reparse guarantee removed from skill and operations guide. |
| F18 | Architecture removes nonexistent JSON parser and adds batch-audit/Markdown-table ownership. |
| F19 | Workflow templates no longer impose executable APIs on all skill types. |
| F20 | Storage mirroring distinguished from explicit source imports. |
| F21 | Shared contracts linked from skills; repeated prescriptions reduced. |
| F22 | Appropriate common structures applied across all 27 documents. |
| F23 | Dated maintenance reminders removed from active skill instructions. |
| F24 | Infrastructure error-type discrepancy remains documented and deferred. |
| F25 | Direct Docling model-call discrepancy remains documented and deferred. |
| F26 | Added metadata, local-link and actual command-parser checks. Semantic coverage still requires review. |
| F27 | Explicit unmatched-name behavior documented; unchanged pending separate contract review. |
| F28 | Earlier approved change restores canonical LinkedIn suggestion filenames; existing files are not migrated. |
| F29 | Original team-profile dependency-content cache gap remains documented and deferred. |
| F30 | Founder-trait and LinkedIn dependency instructions corrected in the People pilot. |

## Batch-audit findings

See the [batch audit](batch-audit-workflows-audit-2026-09-06.md).

| Finding | Current status |
|---|---|
| B01 | Earlier approved implementation makes successful zero-hit retrieval non-blocking for every batch check. Technical errors remain errors. |
| B02 | Earlier approved implementation resolves only the LLM-selected SHA candidate. |
| B03 | Earlier approved general product checklist supplies 14 fallback checks. |
| B04 | User accepted prompt-based Dealum restriction; documentation does not claim a retrieval filter. |
| B05 | Structural validation does not establish complete checklist coverage or provenance; documented, behavior deferred. |
| B06 | Empty exception messages can prevent the intended diagnostic artifact; unresolved implementation issue. |
| B07 | DD and submission failure-result documentation corrected. |
| B08 | Submission's broad local retries and older-artifact fallback disclosed; behavior remains deferred. |
| B09 | Edited internal audits alone do not necessarily invalidate team/SHA synthesis; documented, cache policy deferred. |
| B10 | Replacement versus appended instructions clarified in shared standards. Team prompt scope wording remains deferred; model synthesis quality is not mechanically guaranteed. |

## Ranking findings

See the [ranking audit](ranking-workflows-audit-2026-09-06.md).

| Finding | Current status |
|---|---|
| R01 | Approved startup-profile content freshness implemented earlier. Investor-profile/roster edits alone remain an explicit cache limitation. |
| R02 | User explicitly retained seen-startup deprioritization rather than exclusion; documented. |
| R03 | User explicitly retained duplicate/missing-ID recovery; documented. |
| R04 | Canonical suggestion filename fix implemented earlier; no file migration. |
| R05 | Approved defaults of 16 implemented earlier across APIs, CLIs and harness; explicit overrides preserved. |
| R06 | Approximate tournament and potentially larger final comparison documented; algorithm unchanged. |

## Additional observations from the final pass

The following behavior was traced and documented without changing its contract:

- `startup_profile(files=...)` bypasses reuse but saves under the normal report
  identity; its configuration key does not include supplied file contents.
  A nonempty missing-context response can also be saved. Any cache or evidence
  policy change needs a separate review.
- LinkedIn maintenance's `missing` command can update registry/cache state even
  though it does not scrape. It is not a purely read-only operation.
- Harness dispatch can format an exception as returned error text, allowing a
  one-shot process to exit successfully. Direct CLI and harness failure signals
  are therefore not interchangeable.
- Dealum's batch CLI retains its own execution/error aggregation instead of the
  usual shared runner. Standards disclose this implementation discrepancy.
- Website import preserves the previous snapshot if no HTML is retrieved, but
  successful replacement is not transactional. Its queued-link host restriction
  does not promise that HTTP redirects stay on the original host.
- Invitation contact matching uses email, LinkedIn ID, then normalized name.
  Resolved member contact edits are not independently included in its cache key.
- Maintenance's legacy insight-metadata migration recipes do not establish the
  current cache contract for every skill. They need scoped review before broader use.

## Verification and limits

The new documentation checks validate discovery metadata, maintained local links
and shell examples through the real Typer/Click and harness argument parsers.
They stop before workflow execution. The stale test requiring an old heading was
replaced with a check that the standards skill has no executable entry point.

Verification: **324 tests passed**, including 115 documentation checks, using
`sictic-env`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` and pytest's `pytest_mock` plugin.
The selected suites cover skill harness/CLI, bulk refresh, checklist audits, SHA,
submission, revised team, DD priorities, invitations, member preferences, startup
profiles, website import, dataset maintenance/chat, LinkedIn maintenance and
Dealum import. `git diff --check` passed.

A hash comparison against 357 files captured before this final pass confirms
that application code and configuration are unchanged. The only changed file
in that baseline is the old heading test; the documentation test file is new.
Earlier authorized implementation edits are preserved.

This is not exhaustive semantic verification of every library routine, model
prompt or generated report. No live model, external service, import, deletion,
cache migration or production workflow was run. Remaining behavior conflicts
above are explicit follow-up work, not silently resolved through documentation.
