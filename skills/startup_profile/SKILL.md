---
name: startup_profile
description: Generate a startup diagnostic with sector from a named dataset, including a prepared temporary dossier. Use to explain the business, technology, market and current challenges.
---

# Startup profile

Describe what the startup does and the structural questions requiring review.

## Inputs and outputs

The async `startup_profile(startup)` returns one
`InsightFile` in a list, named `startup-profile-<startup>-<model>.md`.
The fifth bullet, **Classification**, is appended directly from the Dealum result
in the startup_sector JSON insight, using resolved display names. Its sub-bullets
are **Primary-industry**, **Secondary-industries**, **Primary-technology** and
**Secondary-technologies**, preserving the selection order from startup_sector.
The current Dealum reference has no subindustry hierarchy.
Unresolved primary selections are shown as insufficient evidence; empty secondary
lists are shown as "None selected".
Legacy manual SICTIC classifications retain
their explicit SICTIC label; they are not translated into Dealum industries.
Product type is owned by dd_checks and is not added to this profile.
The configured LLM framework covers oneliner, technology, business model and
current challenges; it does not classify the startup.

## Workflow and dependencies

Prepare and synchronize the named startup dataset, then select a manual override
through InsightFile. If no manual profile exists, call startup_sector's existing
`startup_sector_as_dict` adapter so edited manual category IDs receive current
display names and derived fields without rewriting the source file.
Include the Dealum record, rendered classification bullet and profile
configuration in config_key before checking generated-profile reuse; InsightFile
owns hashing and freshness. Classification freshness belongs to startup_sector.
Changes to the other providers alone do not invalidate this profile. For a
legacy manual SICTIC classification, include that legacy classification instead.
Retired product-type fields in older manual classification files are ignored
for profile rendering and freshness, without modifying those files.
Existing generated datasets bypass startup preparation and external imports;
their profiles are saved within that generated dossier.

For supplied documents, follow the shared
[temporary-dataset lifecycle](../standards_and_architecture/SKILL.md#temporary-datasets)
and pass the prepared dataset name. Add further documents for the same startup
to its existing `datasets/` folder without resetting it. The skill accepts no
file-input argument.

Use `dataset_chat` with the four configured questions and prompt, then append
the fifth classification bullet in Python (or the legacy SICTIC sector, with
technologies explicitly unavailable). This adds no LLM call and no separate header.
The registry declares
startup-sector as a prerequisite; direct calls invoke the same public skill.
Direct preparation may import Dealum source data.

## Side effects and failure behavior

Preparation and retrieval may convert/index documents; generation calls a model
and saves a report within the named dossier.
Technical failures (including classification failures) and empty generated output
raise before saving. A direct call returns an existing manual profile without
calling the classification skill.

The insufficient-context sentinel is saved unchanged, without classification
labels, to preserve sentinel detection. It is not
a successful substantive diagnosis. Consumers can inspect
`InsightFile.has_insufficient_context()`.

## Usage

```bash
conda run -n sictic-env python -m skills.harness '/startup_profile "<STARTUP>"'
```

The direct CLI accepts comma-separated `--startups` dataset names. It continues
after individual startup failures, prints successful
reports, then exits with code 1 if any failed. The harness handles one startup.
`--startup` remains a direct CLI alias for `--startups`.

## References

- [Implementation](startup_profile.py), [direct CLI](__main__.py)
- [Configuration](../../config/startup_profile/)
- [Dataset chat](../dataset_chat/SKILL.md)
