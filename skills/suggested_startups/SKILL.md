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

2. **Configuration:**
   * Load the strategic-fit objective from `config_load()["suggested_startups"]`.
   * Build one `config_key()` from the complete suggested-startups, `ranking_top_k`, and `ranking_rationale` config sections plus the selected startups and `max_startups`.
   * Do not copy, parse, embed, or index investor or startup-profile insights.

3. **Per-Investor Output:**
   * For each investor, construct `lib.insights.InsightFile(dataset=dataset_slug, skill="suggested_startups", model=llm_model(), identifier=investor, subdir=True, config_key=suggested_config_key)`.
   * Recompute the ranking whenever the skill is explicitly invoked; ranking outputs do not participate in dataset-revision freshness caching.

4. **Stored Profile Preparation:**
   * Select startup-profile insights with `select_insights(startups, "startup_profile")`; fail before any LLM call if a requested profile is missing or duplicated.
   * Compile those selected `InsightFile` objects into an ID-to-profile mapping without regenerating startup profiles.
   * Load each pending investor's stored investor profile by canonical LinkedIn ID; fail before any LLM call if any profile is missing. Do not refresh investor profiles as a side effect.

5. **Per-Investor Startup Selection:**
   * For each pending investor, rank every selected startup profile with `ranking_top_k`, using its default batch size, the stored investor profile as the objective context, and `max_startups` as `top_k`.
   * Generate balanced rationales for the finalists with `ranking_rationale`, preserving canonical startup IDs throughout.

6. **Output Generation:**
   * Save one Markdown table per investor with `insight.save(content)` only after all validation succeeds.
   * Catch generation, validation, and save errors per investor. Log the full error, do not save that investor's invalid output, and continue processing the remaining investors.
   * Log a final summary with generated and failed counts. Keep this operational summary out of the return value.
   * Log each `insight.path` and return all generated artifacts as
     a flat `list[InsightFile]`. Do not hardcode `<REPO_PATH>/insights/...`
     paths.

## Usage

```bash
conda run -n sictic-env python -m skills.harness /suggested_startups --startups "<startup1>,<startup2>" --investor "<name1>,<name2>"
```
