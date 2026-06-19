---
name: dealum_import
description: Import Dealum application data and linked documents for explicitly named startup datasets or Dealum application codes.
---

# Dealum Import

Use this skill to import a startup application and linked Dealum documents into
the normal SICTIC-AI startup dataset folder.

## Usage

Import one startup:

```bash
python -m skills.dealum_import "Avientus"
```

Import several explicit startups by passing a comma-separated list:

```bash
python -m skills.dealum_import "Avientus, daav, prevision medicine"
```

## Storage

Dealum imports write to:

```text
$LOCAL_STORAGE_PATH/storage/startups/<startup>/datasets/dealum/
```

Expected files include:

* `application.md`
* `application.raw.json`
* `manifest.json`
* `documents/*` for linked Dealum files

To list local startup dataset folders:

```bash
ls "$LOCAL_STORAGE_PATH/storage/startups"
```

## Matching Rules

Startup names are reconciled using an exact normalized Dealum name or an exact
Dealum application code. If multiple Dealum applications match the same startup
name, select the application with the latest available application date.
If no usable dates are present, or if the latest date is tied, report the
ambiguity and ask for a more specific application identifier.

If no exact match exists, ask for the startup name as shown in Dealum or the
application code.

## Reporting

When importing multiple startups, report:

* imported successfully
* ambiguous Dealum matches
* no exact Dealum match
* API or configuration errors

Dealum requires `DEALUM_API_KEY` and `DEALUM_DEALROOM_ID`.
