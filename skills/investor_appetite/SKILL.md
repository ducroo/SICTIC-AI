---
name: investor_appetite
description: Determines the ideal startup profile for one or more investors based on their personal profiles.
---

## Skill Prompt: `investor_appetite`

**Objective:** Analyze the personal profile of an investor to deduce their ideal startup investment profile (appetite). Can process a single investor, a list of investors, or all members if no input is provided.

**Inputs:**
* `investors` (Optional): Can be a single string (name), a list of strings (names), or left empty/None.

**Procedure:**

1. **Input Normalization & Fallback:**
   * If `investors` is empty or `None`, invoke `get_all_members()` from `skills.utils.all_members`. Parse the returned Markdown string (ignoring headers like `#` and empty lines) to extract the full list of member names.
   * If `investors` is a single string, wrap it into a list.
   * Hardcode the target dataset to `"sictic_members"`.

2. **Sequential Processing:**
   * Initialize a result dictionary mapping the investor's name to their generated appetite profile string.
   * For each `investor_name` in the list:
     * **Filename Generation & Caching:**
       * Sanitize `investor_name` into a safe string.
       * Determine the model suffix dynamically via the `DEFAULT_LLM` environment variable.
       * Construct the output file path: `<REPOSITORY_DIR>/insights/sictic_members/investor_appetite/<sanitized_name>_<model_name>.md`.
       * Use the `check_insight_refresh` utility (dataset: `"sictic_members"`, file: `"investor_appetite/<sanitized_name>_<model_name>.md"`). 
       * If a refresh is not needed and the file exists, read its contents, append to the result dictionary, and skip to the next investor.
     * **Retrieve Person Profile:**
       * Call the existing `person_profile` skill (with `name=investor_name` and `dataset_name="sictic_members"`) to fetch their background data.
     * **LLM Generation:**
       * Dynamically load the instructions via `config_load()`: `llm_instructions = config['investor_appetite']['llm_instructions']`.
       * Invoke `llm_chat` with a prompt formatted as: `"Context: <PERSON_PROFILE>\n\nInstructions: <LLM_INSTRUCTIONS>"`.
     * **Output Generation:**
       * Save the resulting LLM text to the constructed output file path.
       * Store the text in the result dictionary.

3. **Return:**
   * Return the fully populated result dictionary.

**CLI Interface:**
* Expose a `typer` CLI in `__main__.py` that accepts an optional list of investor names as arguments.

## Usage

```bash
conda run -n sictic-env python -m skills.investor_appetite [investor_name ...]
```
