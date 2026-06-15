---
name: batch_audit
description: Runs a user-provided Markdown checklist against a dataset and returns a structured audit table.
---

# Batch Audit

Use this skill when the user provides a checklist of questions to answer from a
dataset. The checklist must contain at least one Markdown heading. Questions are
evaluated concurrently and the result is stored as a reusable insight.

## Usage

```bash
python -m skills.batch_audit <dataset> <checklist.md>
```
