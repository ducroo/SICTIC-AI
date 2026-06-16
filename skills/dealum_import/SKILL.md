---
name: dealum_import
description: Import startup applications and linked Dealum documents into the standard SICTIC-AI startup dataset folder. Use when a user asks to import, ingest, or reconcile one or more startups from Dealum by startup name or application code.
---

# Dealum Import

Use this skill to import a startup application and linked Dealum documents into
the normal SICTIC-AI startup dataset folder. Startup names are reconciled using
an exact normalized Dealum name or an exact application code. If neither
matches, ask the user for the name shown in Dealum.

## Usage

```bash
python -m skills.dealum_import "Avientus"
```

Import multiple startups by passing a comma-separated list:

```bash
python -m skills.dealum_import "Avientus, daav, prevision medicine"
```
