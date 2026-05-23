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

1. **Filename Generation & Caching:** 
   * Sanitize the input `name` into a safe string.
   * Construct the output file path: `<GDRIVE_MOUNT>/insights/<dataset_name>/profile_<sanitized_name>_<model_name>.md`.
   * Check if this file already exists using the `check_insight_refresh` utility. If it does, read and return its contents immediately, bypassing the LLM.

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
   * Save the resulting synthesized profile string to the constructed output file path.
   * Return the profile string.

**CLI Interface:**
* Expose a `typer` CLI in `__main__.py` that accepts both `name` and `dataset_name` as required positional arguments.

## Usage

```bash
conda run -n sictic-env python -m skills.person_profile "<NAME>" "<DATASET_NAME>"
```