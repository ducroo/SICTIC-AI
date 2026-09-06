# Requirements for assessing Open WebUI as a RAG backend

Status: assessment criteria accepted by the user on 5 September 2026. See the [Open WebUI and RAGFlow assessment](open-webui-ragflow-assessment.md) for the comparison. Acceptance of these criteria does not establish that either product meets them.

## Purpose and operating baseline

Reduce custom code and setup complexity while preserving the existing investment workflows and investor expertise configuration. Evaluate Open WebUI as a document and retrieval service behind the existing Google Chat bot and skills. Its own chat interface is optional.

Production currently runs successfully on a Mac mini and uses a cloud LLM. Preserve that operating model as the baseline: local document storage and retrieval, with selected context sent to the configured cloud model. A local LLM is not required. Prefer open-source packages; additional cloud services are optional if their cost and data handling are acceptable.

The expected corpus is 100–200 datasets, each containing 20–50 documents of approximately 3–10 pages. This implies 2,000–10,000 documents and approximately 6,000–100,000 pages. Actual ingestion and query performance must be measured on production-equivalent hardware.

## Access and confidentiality

The initial bot users are the operations team. Deal leads may gain bot access later; they already receive access to the relevant startup folder and therefore to insights written there.

| Actor or workflow | Permitted inputs | Output audience and destination |
| --- | --- | --- |
| Operations, working on one startup | That startup's documents and insights | That startup's folder; assume its deal leads can read the output |
| Operations, performing investor matching | The target startup plus investor profiles from `sictic-members` | Startup-specific matching results in the target startup's `insights` folder |
| Operations, comparing multiple startups | The explicitly selected startups and, where required, investor profiles | Operations-only destination; never a startup folder shared with deal leads |
| Deal lead, future bot access | Only startups to which that person has access | Only the authorized startup context and intended recipients |
| System service | Access needed to execute an authorized workflow | Its broad technical access must not determine what a caller can retrieve or what a recipient receives |

Investor matching is an intentional use of information from two sources. The requirement is to allow the intended matching results while keeping the underlying member collection restricted to operations and the system. Deal-lead access to a matching report must not confer direct access to investor profiles. The permitted detail in matching rationales remains an output-policy detail to record before enabling deal-lead bot access; existing shared reports should also be checked against it.

Multi-startup reports require an operations-only destination because the confidentiality requirement prohibits one startup's private information appearing in another startup's shared insights. This is an interpretation of the stated confidentiality rule, not a claim that every existing output path already enforces it.

## Requirements and acceptance criteria

| ID | Requirement | Acceptance criteria |
| --- | --- | --- |
| R1 | Simple installation and administration | One documented installation/start procedure and one main configuration entry point. Provision datasets automatically from the established folder structure. Record all required services and administrative interfaces. No code edits or repeated UI setup for each startup. |
| R2 | Google Chat and existing skill integration | Keep the production Google Chat bot as the everyday interface. Provide documented APIs for ingestion, processing status, scoped search and complete-document access. Existing skills use a small adapter and retain their structured-output validation. |
| R3 | Enforced startup scope | Bind each startup task to an explicit startup identifier outside the language model. Apply that scope to searches, document reads, tool calls, prompts, history, caches, retries and output paths. Missing or ambiguous scope stops the operation; it never broadens the search. Document text cannot grant access to another dataset. |
| R4 | Separation independent of bot credentials | A bot credential that can access all datasets must not make global retrieval available to an ordinary startup task. Validate that returned documents belong to the permitted input scope. Restrict multi-startup workflows to operations and their designated private outputs. Separate collections or dataset filters are implementation choices whose enforcement must be verified. |
| R5 | Preserve the shared startup folder | Retain `startup_slug/datasets/` and `startup_slug/insights/` as the source and output layout. Startup-specific outputs go to the corresponding insights folder. Keep shared indexes, credentials and other datasets outside the folder shared with deal leads. Files remain usable without the RAG application's UI. |
| R6 | rclone owns cloud file synchronization | Read source files locally and write insights locally. Following completed synchronization, detect additions, modifications, renames and deletions. Avoid duplicate ingestion and partially written files. Expose processing failures and support safe retries. No additional Google Drive connector is required. |
| R7 | Search and complete-document access | Support passage retrieval with source attribution, complete extracted document retrieval, and original-file access. A skill can move from a search hit to the complete corresponding document without gaining access to other datasets. Complete extraction includes all successfully processed pages and sheets; omitted or failed content is reported. Context limits are handled explicitly rather than silently truncating a document. |
| R8 | Preserve extraction quality | Evaluate representative PDFs, scans, Word documents, presentations, spreadsheets and Markdown from the existing corpus. Check multi-sheet workbooks, table structure, numeric values, dates, percentages and cached formula results. Report extraction errors and absent formula results. Docling and Qdrant are replaceable if the alternative meets the quality and operating requirements. |
| R9 | Preserve expertise and workflow behavior | Keep investor expertise, prompts and ranking criteria in editable, version-controlled configuration. Preserve full-profile matching, required structured outputs, manual insight precedence and necessary validation. Assess representative existing workflows; a document-chat demonstration alone is insufficient. |
| R10 | Freshness and traceability | Know which source revision has finished processing. After a successful refresh, obsolete source content is no longer retrievable. Detect insights made stale by changed documents or expertise configuration and regenerate them when required. Retain source references, including pages or sheets where available. A failed refresh must not masquerade as current data. |
| R11 | Scale and production fit | Support 200 independently scoped datasets and the estimated upper corpus size. Measure initial ingestion, incremental refresh, search latency, concurrency, RAM and disk use on production-equivalent hardware. Demonstrate recovery after a restart without duplicating or unnecessarily reprocessing the corpus. |
| R12 | Preserve the local/cloud boundary | Keep the document corpus and retrieval service local by default. Continue using the configured cloud LLM with the context needed for an authorized task. Identify any additional external processing, telemetry or content storage introduced by a replacement. Do not require a new hosted retrieval service or local LLM. |
| R13 | Quantified simplification and cost | Report custom lines removed minus all new adapter, synchronization and access-control code. Count services and configuration as well as code. Distinguish deleted logic from logic moved into a workflow editor. Compare monthly LLM and service costs with the current system using representative tasks. State license conditions that affect the intended deployment. |
| R14 | Portable data and recovery | Preserve original files, shareable insight files and expertise configuration outside proprietary application state. Document backup and restoration of any essential dataset mapping or access configuration. Search indexes must be rebuildable from retained source data. |

## Delivery phases

Phase 1 is operations-only bot access. Startup scope and output separation are required immediately because deal leads already read shared startup folders. Do not require a new deal-lead login interface for this phase.

Phase 2 adds deal-lead bot access. Before enabling it, bind Google Chat identity to permitted startups and enforce those permissions on every request and tool call. Validate the recipients of the chat response as well as the invoking user. Deal leads must not access `sictic-members` through search, full-document APIs, generic tools or conversation history. Reuse of a broadly privileged service account must not bypass these restrictions.

Whether deal leads may invoke a restricted investor-matching workflow themselves is a separate future product decision; it is not implied by permission to read an existing matching report.

## Evaluation examples

1. Put distinct confidential facts into two startup datasets, including files with identical names. Exercise passage search, original-file reads, complete-document reads, sequential conversations, concurrent jobs and retries. The other startup's facts must not enter the task context or shared output.
2. Try absent startup identifiers, incorrect document identifiers and instructions inside documents that request another dataset. Verify that the application enforces the allowed scope independently of the model's response.
3. Run investor matching for startup A using member profiles. Verify that the intended result is saved under A, no private startup B content enters the task, and the output follows the agreed member-information disclosure policy.
4. Add, edit, rename and delete local source files through the synchronization routine. Verify document identity, refresh status, removal of obsolete searchable content and stale-insight detection.
5. Retrieve a known document in full and check first and last pages, all expected sheets and representative financial tables. Compare extraction and workflow outputs against the existing implementation with a fixed evaluation set.
6. Run an operations-only multi-startup report. Verify that it is unavailable from any deal-lead-shared startup folder or startup-scoped retrieval path.

These checks provide evidence for the isolation design; a passing test set alone is not proof that every possible disclosure path is closed.

## Details still to measure or specify

- Production Mac mini model, architecture, RAM and available disk space.
- Current monthly model spend and the acceptable additional monthly cost; no numeric ceiling has been specified.
- Required document freshness, response times and simultaneous jobs. Use measured current behavior as the initial comparison baseline.
- How the production Google Chat bot currently establishes startup scope. Its production configuration has not been inspected here.
- Permitted investor-profile details in shared matching results and, for phase 2, identity-to-startup permissions.

## Assessment format

For each requirement, record: built in, configuration required, custom code required, or unsupported. Include version-specific evidence, verification results, remaining work and estimated net code reduction. Keep phase 2 requirements distinguishable from the initial deployment requirements.

Evaluate this contract against Open WebUI before choosing a replacement. A replacement must show a practical benefit over the working Mac mini setup; fulfilling the requirements is necessary but does not by itself justify migration.
