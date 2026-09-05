---
name: person_profile
description: Collate a comprehensive profile on a specific person by searching a given dataset, returning the full synthesized report.
---

## Skill Prompt: `person_profile`

**Objective:** Collate a comprehensive profile on a specific person by searching a given dataset, returning the full synthesized report.

**Inputs:**
* `name`: A string representing the person's name (e.g., `"John Doe"`).
* `dataset_name`: The target dataset to search (e.g., `"fabas"`).

**Procedure:**

1. **Insight File & Caching:**
   * Resolve the person to its canonical identifier through the standard person-resolution flow.
   * Construct the profile insight with `lib.insights.InsightFile(dataset=dataset_slug, skill="person_profile", model=<model>, identifier=<person_identifier>, subdir=True, config_key=<query_and_instructions>)`.
   * Use `insight.find(selection="reusable")` and `insight.content()` to reuse a fresh existing profile when available; otherwise generate the profile and persist it with `insight.save(...)`. Do not hardcode `<REPO_PATH>/insights/...` paths.

2. **Data Retrieval & Synthesis:**
   * Read the existing manual roster and enrich its people through `LinkedInResolver`.
   * Synchronize the dataset before checking profile freshness.
   * Load `query`, `llm_instructions`, and `founder_traits_instructions` via
     `load_repository_config("person_profile")`; both instruction sections always
     form the standard prompt and freshness key.
   * On a cache miss, use `build_person_dossier` for dataset evidence when
     `include_dataset_context` is enabled, add the resolved LinkedIn payload,
     and synthesize through `generate_markdown`.

3. **Output Generation:**
   * Save every synthesized profile through `InsightFile`.
   * `person_profile(...)` returns a flat `list[InsightFile]`.
   * `person_profile_as_person_objects(...)` runs the same workflow and returns
     the populated `list[Person]` required by person-oriented composition.

**CLI Interface:**
* Expose this skill through the shared slash-command harness.

## Usage

Both `person_profile(...)` and `person_profile_as_person_objects(...)` use the
same standard generation workflow: read the authoritative manual roster, resolve
LinkedIn profiles, gather dataset evidence, and apply the configured biographical
and founder-trait instructions. Founder traits are assessed for explicitly
identified active founders; unsupported assessments report insufficient information.
A missing roster raises an error directing the caller to run `persons_in_dataset`;
profile generation never discovers people.

Every profile uses `<identifier>-<model>.md`, with the identifier selected by
`Person.identifier`: LinkedIn ID, otherwise email address, otherwise full name,
using standard slugification. The retained `include_dataset_context` option affects
freshness metadata, never filenames. Manual overrides retain their normal precedence.

```bash
conda run -n sictic-env python -m skills.harness /person_profile "<DATASET_NAME>" "<NAME>"

conda run -n sictic-env python -m skills.person_profile \
  --dataset "<DATASET_NAME>" \
  --person "<NAME_1>, <NAME_2>"
```

Person discovery is owned by `skills/persons_in_dataset`. This skill uses the library roster reader, then gathers evidence and writes individual profiles. Only an explicit discovery run creates a missing roster.
