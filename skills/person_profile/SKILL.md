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
   * If the cache misses, dynamically load the following via `load_repository_config("person_profile")`:
     * **Query:** `config['person_profile']['query']` (The question/prompt string to search for the person).
     * **Instructions:** `config['person_profile']['llm_instructions']` (The strict formatting instructions for the LLM).
   * Invoke `dataset_chat` with the following parameters:
     * `dataset_name=dataset_name`
     * `questions=query.format(name=name)`
     * `llm_instructions=llm_instructions`
     * `return_full_docs=True`
     * `max_chunks=25`

3. **Output Generation:**
   * Save every synthesized profile through `InsightFile`.
   * `person_profile(...)` returns a flat `list[InsightFile]`.
   * `person_profile_as_person_objects(...)` runs the same workflow and returns
     the populated `list[Person]` required by person-oriented composition.

**CLI Interface:**
* Expose this skill through the shared slash-command harness.

## Usage

For composition without public enrichment, call `person_profile(...)` or
`person_profile_as_person_objects(...)` with `allow_public_sources=False`.
This requires the existing manual persons roster and skips LinkedIn resolution.
A missing roster raises an error directing the caller to run `persons_in_dataset`;
profile generation never discovers people. Set `assess_founder_traits=True` to append
the configured narrative N001 assessment for explicitly identified active
founders. These options use separate profile cache identifiers; default
callers retain the existing enriched profile behaviour.

```bash
conda run -n sictic-env python -m skills.harness /person_profile "<DATASET_NAME>" "<NAME>"

conda run -n sictic-env python -m skills.person_profile \
  --dataset "<DATASET_NAME>" \
  --person "<NAME_1>, <NAME_2>"
```

Person discovery is owned by `skills/persons_in_dataset`. This skill uses the library roster reader, then gathers evidence and writes individual profiles. Only an explicit discovery run creates a missing roster.
