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
   * If the cache misses, dynamically load the following from `config.json` via `config_load()`:
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

```bash
conda run -n sictic-env python -m skills.harness /person_profile "<DATASET_NAME>" "<NAME>"

conda run -n sictic-env python -m skills.person_profile \
  --dataset "<DATASET_NAME>" \
  --person "<NAME_1>, <NAME_2>"
```
