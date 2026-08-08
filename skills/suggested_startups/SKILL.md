---
name: suggested_startups
description: Rank a provided list of startups against a list of investors by matching startup value propositions with investor professional backgrounds and interests.
---

## Skill Prompt: `suggested_startups`

**Objective:** Rank a provided list of startups against a list of investors by matching startup value propositions with investor professional backgrounds and interests.

**Inputs:**

* `dataset_name` (Optional, Default=`"sictic_members"`): Community dataset containing investors.
* `startups` (Optional): Startup names to consider. If omitted, discover startup datasets dynamically.
* `investors` (Optional): Investor names to process. If omitted, resolve all persons from the dataset with `LinkedInResolver`.
* `max_startups` (Optional, Default=5): Maximum suggested startups per investor.

**Procedure:**

1. **Input Resolution:**
   * Slugify `dataset_name`.
   * If `investors` is empty, resolve all persons with `LinkedInResolver(dataset_slug).get_all_persons()`.
   * If `startups` is empty, discover startup datasets with `list_dataset_names("startups")`, excluding configured community and ignored datasets from `config_load()["bulk_refresh"]`.

2. **Configuration & Sync:**
   * Load `prompt_template = config_load()["suggested_startups"]["suggested_startups_prompt"]`.
   * Build `datasets_to_check = [dataset_slug] + [slugify(startup) for startup in startups]`.
   * Run `sync_datasets(datasets_to_check, raise_on_error=True)` so investor and startup indexes are current.

3. **Per-Investor Insight Cache:**
   * For each investor, construct `lib.insights.InsightFile(dataset=dataset_slug, skill="suggested_startups", model=llm_model(), identifier=investor, subdir=True, source_datasets=datasets_to_check, prompt_key=prompt_template)`.
   * Use `insight.find(selection="reusable")` to skip investors whose suggested-startups report is already fresh.

4. **Startup and Investor Profile Preparation:**
   * Compile startup profiles in memory with `compile_startup_profiles(startups)`, which calls `startup_profile(startup)` for each selected startup and combines the profile text into a single prompt context.
   * Refresh investor profiles with `investor_profile(source_dataset=dataset_slug)`.
   * Load the selected investors' reusable investor profiles with `read_investor_profiles(dataset_slug, names_to_process)`. These profiles combine person profiles with investment track records and preferences.

5. **Per-Investor Startup Selection:**
   * For each investor with an available investor profile, call `process_single_investor(investor, profile_text, compiled_startups, prompt_template, max_startups)`.
   * `process_single_investor` calls `llm_chat`, parses the JSON-like ranking response with `repair_json_payload`, sorts by rank, and keeps the top `max_startups`.

6. **Output Generation:**
   * Save one Markdown table per investor with `insight.save(content)`.
   * Log each `insight.path` and return all generated or reusable artifacts as
     a flat `list[InsightFile]`. Do not hardcode `<REPO_PATH>/insights/...`
     paths.

## Usage

```bash
conda run -n sictic-env python -m skills.harness /suggested_startups --startups "<startup1>,<startup2>" --investors "<name1>,<name2>"
```
