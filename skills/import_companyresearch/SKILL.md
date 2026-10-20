---
name: import_companyresearch
description: Import a CompanyResearch report once for a Swiss startup, or sweep pending requests into their associated dossiers without waiting for research.
---

# CompanyResearch import

Use `import_companyresearch(startup=None, *, uid=None, company_name=None)` from
Python. The async function returns `list[CompanyResearchImportResult]`, containing
the results touched by the sweep and the requested startup. This is source
acquisition, not an InsightFile-producing skill.

## Workflow

1. Collect locally registered requests that the provider has already accepted.
   Download completed reports into their registered dossiers; leave active requests
   pending. Log collection errors and continue with other dossiers, returning an
   explicit error result. Finish collection before attempting held submissions.
2. Without `startup`, proceed to the submission sweep below. A UID or company name
   without a destination startup is an argument error.
3. For a startup with a completed import, return it unchanged alongside sweep
   results. For a registered request, reuse its identity and operation key.
4. Otherwise use the explicit `uid`, bypassing all evidence gathering and LLM
   calls. Without one, scan source text and available parsed sources through the
   shared enumeration/chunking helpers. Extract UID mentions and their context.
   Lookup those UIDs through CompanyResearch; only when none were found use the
   startup/company name, configured aliases and explicitly labelled legal names.
   One `generate_json` call selects a registry candidate using dossier evidence.
   No candidates, missing identity evidence or unresolved identity raises an error.
   The model cannot select a UID outside the candidate list. There is no second
   discovery LLM call or alternative-name research loop.
5. Persist a newly resolved dossier/UID/idempotency-key association as `on_hold`.
   Company lookup uses a separate endpoint and can resolve identities while
   research capacity is full (ordinary lookup rate limits still apply).
6. Submit held requests oldest first, using registry insertion order and
   `refresh=false`. Mark each `submitting` before POST and save its receipt
   immediately on acceptance. On HTTP 429 `concurrency_limit`, put that request
   back `on_hold` and stop further submissions for this invocation. Log the hold
   as normal progress, without waiting, repeated retries or an error result.
   Other errors retain their existing error/exception behavior.
7. Save an immediately available report; otherwise return without polling or
   waiting for research. A later invocation collects it and tries held requests.

Source evidence does not call startup_profile, fetch websites/Dealum, or trigger
ingestion. Unparsed binary documents become available after ordinary ingestion.
Evidence and lookup budgets are in `config/import_companyresearch/settings.json`.
Identity ambiguity is an error, never an automatic guess.

## Persistence and concurrency

Completed imports contain `report.json` (original structured response) and
`report.md` (deterministic rendering of all fields, including sources and evidence)
under `<startup>/datasets/companyresearch-ch/`. No model call renders the report.
The report and receipt UIDs must match the requested UID before publication.
Snapshots use the shared atomic directory replacement helper. Both files identify
a completed snapshot; empty/partial output does not block recovery.

The registry is `cache/import_companyresearch/requests.json` in runtime storage,
outside ingestible datasets. Its keys are canonical dossier slugs; records retain
UID, idempotency key, request ID and status. Shared atomic writes and a filesystem
lock serialize importer calls across processes on this installation. The lock is
acquired in a worker thread, so it cannot block an async caller's event loop.
Separate installations do not share this runtime registry; collect requests on
the installation that submitted them.

`on_hold` is a local queue state; `queued` means accepted by CompanyResearch.
Old or interrupted `submitting` entries without a receipt remain retryable using
their original keys; they are not assumed rejected after a transport failure.
There is no free-slot API or hardcoded remote concurrency limit: the first
capacity rejection stops that invocation's submission sweep. New startup calls
can still register identities without waiting for capacity.

There is no refresh option, age-based reimport, automatic resubmission after
terminal provider failure, or automatic research completion monitor. Failed,
cancelled and expired requests remain recorded and require operator investigation.
A report-download/publication failure remains retryable through its existing
receipt. The API's default cached report can be old; the provider research date
remains in the output. No indexing or dataset activation occurs here.

## API and credentials

Read `companyresearch_api_key` (or `COMPANYRESEARCH_API_KEY`) through `get_env_var`;
never log the key. Account
permissions need companies:read, research:write and reports:read. The adapter owns
HTTP access, response-schema validation and structured InfrastructureError failures.
HTTP 429/503 use shared transient retries and honour Retry-After, except for
HTTP 429 `concurrency_limit`, which is exposed as a structured capacity error for
the local queue to handle without retry delays. This retry handling
is separate from research polling: research itself is never waited for. The remote
API enforces account-wide job limits; rejected submissions keep their idempotency
key for a later sweep. No local scheduler lease represents a five-minute remote job.

`api_schema.json` contains the provider response schemas fetched from
https://api.companyresearch.ch/api/openapi.json on 2026-10-20 (API 1.0.0), with
references rewritten to local `$defs`. It is a boundary-validation contract,
not an LLM schema. The endpoint and timeout are configuration, not skill constants.

## Usage

```bash
conda run -n sictic-env python -m skills.import_companyresearch avientus
conda run -n sictic-env python -m skills.import_companyresearch avientus --uid CHE-123.456.789
conda run -n sictic-env python -m skills.import_companyresearch avientus --company-name "Avientus AG"
# Collect accepted requests and submit locally held requests:
conda run -n sictic-env python -m skills.import_companyresearch
```

An external caller can run the sweep command every five minutes. The skill does
not schedule itself or keep a polling process alive.

UID above is illustrative. CLI results are JSON operational statuses and paths;
errors/terminal failures produce exit code 1; pending and `on_hold` requests exit
successfully.
The harness accepts `/import_companyresearch [startup] [--uid UID] [--company-name NAME]`.
This first implementation does not add automatic acquisition to bulk_refresh or
other skills. Call the public API or CLI explicitly, and run normal dataset
synchronization when the imported report is needed for retrieval.
