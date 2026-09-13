---
name: captable_build
description: Extract, reconcile and validate startup ownership and convertible-loan data into four managed JSON insights.
---

# captable_build

## Inputs and outputs

One startup dataset slug with successfully synchronized parsed documents.
The canonical API returns `list[InsightFile]` containing the consolidated result.
Four logical JSON insights live under `insights/captable-build/`: `classification`,
`loan-extraction`, `table-extraction`, and `consolidated`. Filenames and model
suffixes are supplied by `InsightFile`, using `subdir=True` and `extension="json"`.
There are no dated snapshots, latest pointers, HTML files, separate assessments,
aggregation caches or build Markdown reports. Source dates stay inside the JSON.

## Workflow and dependencies

Classify source documents, extract CLA terms, and extract cap-table/register/pool
versions. Reconcile the source versions, assess terms and aggregate loans in code,
then save the consolidated JSON. Assessment and aggregation have no separate files;
PDF signature markers are read again when consolidation must be recomputed.
The configurable term schema is `config/captable_build/cla_terms.md`.

Every stage uses shared reusable selection: manual first, then ranked generated
insights with matching indexed startup revision and effective configuration.
Extraction keys include selected classification content. Consolidation includes
all three selected inputs, assessment settings, tool version and evaluation date
for maturity findings. Artifact schema configuration is included in every stage's
freshness key. Editing a manual input invalidates generated dependents.
A manual consolidated JSON wins before dependencies run. `--fresh` bypasses
only generated reuse, without deleting files or overriding manual inputs.

## Validation convention

Follow the shared [JSON validation rule](../standards_and_architecture/SKILL.md#model-calls).
Classification and extraction use `generate_json`, which already validates
their response schemas. Do not duplicate those structural checks immediately
after generation. Loaded artifacts and assembled outputs use
`validate_json_schema` through `lib.captable.schema.validate_build_artifact`.
`config/captable_build/artifact_schemas.json` defines the saved envelopes and
calculated fields. The schema builder reuses the classification, CLA, cap-table,
register and pool response schemas, adding the dataset/document metadata written
by the pipeline. CLA fields continue to follow `cla_terms.md`.

Validation runs before an assembled artifact is saved and whenever one is read,
including manual and cached data. Required fields, nested types, enums and empty
failure lists are schema constraints. Invalid outputs raise before replacing a
previous artifact. An absent cap table remains representable, with empty ownership
data and a domain finding; missing evidence is not a structural error.

Keep ownership totals, cross-document reconciliation, duplicate-record checks
and financial consistency in domain code. Schema validation does not establish
those relationships or the accuracy of extracted evidence.

Extracted table rows are reviewed by `lib/captable/table_evidence.py` before
the JSON is accepted: every quoted line must resolve to one source row or
passage, numbers must come from source cells of rows that name the holder,
sums cover every quoted row of a holder in one column, zero needs a dash or a
literal 0, and blanks or absent columns are null. Share classes and pools may be
named on another quoted row of the same sheet or by a header; a pool's third
figure may be derived from the two stated ones. Rejections are fed back to the
model with the numbers the quoted cells state, the quoted rows that were ignored
because they do not name the holder, and the closest source line; the evidence
rules are described in `docs/captable.md`.

## Side effects and failure behavior

Generation writes only the managed JSON insights and shared freshness metadata.
Missing/empty parsed sources or failed extractions raise; incomplete outputs are
not saved as reusable insights. Failures remain in logs and retry on a later run.
Manual JSON must have the same structure as its generated counterpart. Existing
legacy files are left untouched and are not selected as alternative inputs.
This skill never imports, synchronizes or discovers people implicitly. Bulk
refresh performs its own shared pre-ingestion and registers this for startups.

## Usage

```bash
conda run -n sictic-env python -m skills.harness /captable_build example
conda run -n sictic-env python -m skills.captable_build build --startup example
```

`--dataset`/`-d` remain aliases; `--fresh` regenerates generated artifacts.
The direct CLI retains `classify`, `extract`, `table`, `assess`, and `aggregate`
for inspection. They use the same stage implementations; cheap assessments and
aggregation only return structured data. The `build` Python adapter returns the
consolidated dictionary from the same canonical workflow. No `snapshot` command.
The direct build CLI also retains `--model` for explicit test-model overrides.

## References

- [Implementation](captable_build.py)
- [Insight objects](../../lib/captable/insights.py)
- [Table evidence rules](../../lib/captable/table_evidence.py)
- [Artifact schema composition](../../lib/captable/schema.py)
- [Artifact schemas](../../config/captable_build/artifact_schemas.json)
- [Term schema](../../config/captable_build/cla_terms.md)
- [Domain checks](../../docs/captable-checks.md)
