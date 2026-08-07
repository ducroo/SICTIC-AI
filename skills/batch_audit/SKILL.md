---
name: batch_audit
description: Runs a structured Markdown checklist against a dataset and saves a reusable JSON audit Insight.
---

# Batch Audit

Use this skill when the user provides a checklist of questions to answer from a
dataset. The checklist uses a level-one title, level-two chapters, level-three
checks, prose descriptions, and optional `**Keywords:**` lines. Checks are
evaluated concurrently and the canonical JSON result is stored as a reusable,
freshness-tracked Insight under the dataset's `insights/batch-audit/` directory.
Calling skills render their human-facing reports with
`json_to_markdown_table`.

If the level-one title starts with a number, such as `# 2 Corporation-General`,
that number prefixes the generated chapter and check numbers (`2.1`, `2.1.1`).
Unnumbered checklist titles use local numbering (`1`, `1.1`).

The calling skill supplies its allowed status scale. Every completed check uses
the common fields `number`, `check`, `status`, `rationale`, `source_documents`,
and `proposed_next_steps_and_questions`. Technical failures are recorded in the
separate `error` field.

## Usage

```bash
python -m skills.batch_audit <dataset> <checklist.md> --skill-name <calling_skill>
```

The calling skill determines the filename prefix. For example,
`--skill-name dd_checks` writes
`insights/batch-audit/dd-checks-<checklist>-<model>.json`.
