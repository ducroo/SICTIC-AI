---
name: suggested_startups
description: Rank a provided list of startups against a list of investors by matching startup value propositions with investor professional backgrounds and interests.
---

## Skill Prompt: `suggested_startups`

**Objective:** Rank a provided list of startups against a list of investors by matching startup value propositions with investor professional backgrounds and interests.

**Inputs:**

* `dataset_name` (Optional, Default=`"sictic_members"`): Community dataset containing investors.
* `startups` (Optional): Startup names to consider. If omitted, discover startup datasets dynamically.
* `investors` (Optional): Investor names or LinkedIn IDs to process. If omitted, use all canonical persons with LinkedIn IDs from `persons_in_dataset`.
* `max_startups` (Optional, Default=5): Maximum suggested startups per investor.

**Procedure:**

1. **Input Resolution:**
   * Slugify `dataset_name`.
   * Resolve investors to canonical `Person` objects from `persons_in_dataset(dataset_slug)` and preserve their LinkedIn IDs throughout profile lookup.
   * If `startups` is empty, discover startup datasets with `list_dataset_names("startups")`, excluding configured community and ignored datasets from `config_load()["bulk_refresh"]`.

2. **Configuration & Sync:**
   * Load the prompt and JSON response schema from `config_load()["suggested_startups"]`.
   * Build one `config_key()` from the complete suggested-startups config section so future config files participate in Insight freshness automatically.
   * Build `datasets_to_check = [dataset_slug, "available-startup-profiles"]`.
   * Run `sync_datasets(datasets_to_check, raise_on_error=True)` so investor and selected startup-profile indexes are current.

3. **Per-Investor Insight Cache:**
   * For each investor, construct `lib.insights.InsightFile(dataset=dataset_slug, skill="suggested_startups", model=llm_model(), identifier=investor, subdir=True, source_datasets=datasets_to_check, config_key=suggested_config_key)`.
   * Use `insight.find(selection="reusable")` to skip investors whose suggested-startups report is already fresh.

4. **Stored Profile Preparation:**
   * Select startup-profile insights with `dataset_from_insight("available-startup-profiles", startups, "startup_profile")`; fail before any LLM call if a requested profile is missing or duplicated.
   * Compile those selected `InsightFile` objects into one prompt context without regenerating startup profiles.
   * Load each pending investor's stored investor profile by canonical LinkedIn ID; fail before any LLM call if any profile is missing. Do not refresh investor profiles as a side effect.

5. **Per-Investor Startup Selection:**
   * For each pending investor, call `generate_report` with the stored profile, prompt, schema, candidate startups, and `max_startups`.
   * Supply the schema to LiteLLM as a strict structured-output response format, always run `repair_json_payload`, then apply JSON Schema and request-specific business validation.

6. **Output Generation:**
   * Save one Markdown table per investor with `insight.save(content)` only after all validation succeeds.
   * Catch generation, validation, and save errors per investor. Log the full error, do not save that investor's invalid output, and continue processing the remaining investors.
   * Log a final summary with cached, generated, and failed counts. Keep this operational summary out of the return value.
   * Log each `insight.path` and return all generated or reusable artifacts as
     a flat `list[InsightFile]`. Do not hardcode `<REPO_PATH>/insights/...`
     paths.

## Usage

```bash
conda run -n sictic-env python -m skills.harness /suggested_startups --startups "<startup1>,<startup2>" --investors "<name1>,<name2>"
```
