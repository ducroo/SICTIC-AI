---
name: startup_profile
description: Generate a neutral five-part startup diagnostic from dataset evidence or supplied files. Use to explain the business, technology, market and current challenges.
---

# Startup profile

Describe what the startup does and the structural questions requiring review.

## Inputs and outputs

The async `startup_profile(startup, files=None)` returns one
`InsightFile` in a list, named `startup-profile-<startup>-<model>.md`.
The configured framework covers oneliner, industry, technology, business model
and current challenges; keep detailed assessment instructions in configuration.

## Workflow and dependencies

Prepare the startup dataset and synchronize it, even when files are supplied.
With no files, select a manual override or reusable generated report using indexed
startup revisions and the configured query/instructions.

With files, prepare the existing ephemeral dataset and analyze those documents.
This path bypasses output reuse and still saves under the startup's normal
profile identity. Its cache metadata does not include the supplied file content;
do not interpret that metadata as proof of file-input freshness.

Use `dataset_chat` with the configured questions and prompt. The registry has
no profile prerequisite; direct preparation may import Dealum source data.

## Side effects and failure behavior

Preparation and retrieval may convert/index documents; generation calls a model
and saves a report. Supplied files can replace the current model's startup report.
Technical failures and empty generated output raise before saving.

A nonempty insufficient-context sentinel can be saved as the profile; it is not
a successful substantive diagnosis. Consumers can inspect
`InsightFile.has_insufficient_context()`.

## Usage

```bash
conda run -n sictic-env python -m skills.harness '/startup_profile "<STARTUP>"'
```

The direct CLI accepts comma-separated `--startup` names and repeated `--files`
options. It continues after individual startup failures, prints successful
reports, then exits with code 1 if any failed. The harness handles one startup.

## References

- [Implementation](startup_profile.py), [direct CLI](__main__.py)
- [Configuration](../../config/startup_profile/)
- [Dataset chat](../dataset_chat/SKILL.md)
