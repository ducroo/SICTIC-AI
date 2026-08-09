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

1. **Dataset Preparation:**
   * Convert `startup_name` to a dataset slug with `slugify(...)`.
   * Resolve and prepare the startup dataset with `ensure_startup_dataset(...)`.
   * Run `sync_datasets([dataset_slug], raise_on_error=True)` so OCR and embeddings are current before analysis.

2. **Configuration Loading:**
   * Call `config_load()` and extract:
     * `query = config["startup_traction"]["query"]`
     * `llm_instructions = config["startup_traction"]["llm_instructions"]`

3. **Insight File & Caching:**
   * Construct the traction insight with `lib.insights.InsightFile(dataset=dataset_slug, skill="startup_traction", model=llm_model(), prompt_key=query + llm_instructions)`.
   * Use `insight.find(selection="reusable")` and `insight.content()` to reuse a fresh existing traction report when available.

4. **Data Retrieval, Synthesis & Output:**
   * Invoke `dataset_chat(dataset_name=dataset_slug, questions=query, llm_instructions=llm_instructions, max_chunks=100, strict_insufficient_context=False)`.
   * If there is insufficient indexed context, raise an error and do not save an insight.
   * Save the Markdown result with `insight.save(result)`, log `insight.path`,
     and return `[insight]`.

## Architecture Constraints
* **Entry Point:** Must have a `__main__.py` containing a Typer CLI that accepts `startup_name` as an argument. The CLI must contain zero business logic. 
* **Core Logic:** The core logic must live in `startup_traction.py` under the
  function `async def startup_traction(startup_name: str) -> InsightResult:`.
* **Error Handling:** Use standard Python exceptions internally, caught only by the Typer CLI in `__main__.py`.

## Usage

```bash
conda run -n sictic-env python -m skills.harness /startup_traction "<STARTUP_NAME>"
```
