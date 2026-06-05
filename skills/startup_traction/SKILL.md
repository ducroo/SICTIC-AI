---
name: startup_traction
description: Extracts, analyzes, and summarizes all commercial traction and agreements (LoIs, MoUs, Pilot agreements) from a startup's data room into a structured overview table and synthesis.
---

# Startup Traction & Commercial Agreements Summarizer

## Description
This skill extracts, analyzes, and summarizes all commercial agreements (LoIs, MoUs, Pilot agreements, pre-contracts, partnerships) and traction metrics from a startup's data room. It relies on the `dataset_chat` utility to semantically search for the relevant agreements and run the analysis, returning a formatted Markdown table and synthesis.

## Trigger
Use this skill when the user asks to summarize, extract, or list traction, commercial agreements, LoIs, MoUs, or partnerships for a specific startup.

## Inputs
* `startup_name`: A string representing the startup's name (e.g., `"fabas"`). This directly corresponds to the dataset name.

## Workflow

1. **Filename Generation & Caching:** 
   * Convert `startup_name` to lowercase. 
   * Determine the current model suffix (e.g., `qwen3.5_9b`). 
   * Construct the output file path: `<REPO_PATH>/insights/<startup_name>/<startup_name>_traction_<model_name>.md`. 
   * Call `check_insight_refresh([startup_name], "<startup_name>_traction_<model_suffix>.md")`. If it returns `False` (no refresh needed), read the existing file from disk and return its contents immediately.

2. **Configuration Loading:** 
   * If a refresh is needed, call `config_load()` and extract: 
     * `query = config['traction']['query']` 
     * `llm_instructions = config['traction']['llm_instructions']`

3. **Data Retrieval & Synthesis:** 
   * Invoke `dataset_chat` with the following parameters: 
     * `dataset_name = startup_name.lower()` 
     * `questions = query` 
     * `llm_instructions = llm_instructions` 
   * *Note:* Ensure `dataset_chat` returns the raw Markdown string directly, as we expect a combined table and synthesis rather than a strictly parsed JSON object.

4. **Output Generation:** 
   * Ensure the output directory `<REPO_PATH>/insights/<startup_name>/` exists. 
   * Write the returned Markdown string to the constructed output file path. 
   * Log success using the centralized `logger`. 
   * Return the raw Markdown string to the user/CLI.

## Architecture Constraints
* **Entry Point:** Must have a `__main__.py` containing a Typer CLI that accepts `startup_name` as an argument. The CLI must contain zero business logic. 
* **Core Logic:** The core logic must live in `startup_traction.py` under the function `def startup_traction(startup_name: str) -> str:`. 
* **Error Handling:** Use standard Python exceptions internally, caught only by the Typer CLI in `__main__.py`.

## Usage

```bash
conda run -n sictic-env python -m skills.harness /startup_traction "<STARTUP_NAME>"
```
