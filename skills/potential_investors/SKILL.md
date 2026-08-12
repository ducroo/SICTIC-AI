---
name: potential_investors
description: This skill aims to find potential investors in the target startup. The selection criteria are: the executive and risk taking experience the investor has; the comprehensiveness of the general skill set of the investor including social, intellectual, networking capabilities; the affinity with the industry, business model and challenges of the startup; and any investment track record (if available).
---

## Skill Prompt: `potential_investors`

**Objective:** Match a specific startup against the SICTIC investor base, leveraging investor profiles that combine professional experience with investment track records and preferences.

**Inputs:**
* `startup_name` (Required): The startup to match.
* `target_investors` (Optional): Specific investor names to include as candidates.
* `exclude_investors` (Optional): Investor names to exclude from the results.
* `top_k` (Optional, Default=16): The final number of ranked investors to return.

**Procedure:**

1. **Dataset Preparation:**
   * Convert `startup_name` to a dataset slug with `slugify(...)`.
   * Resolve the startup dataset with `ensure_startup_dataset(...)`.
   * Build the generated `sictic-members-investor-profile` dataset with `dataset_from_insight("sictic-members-investor-profile", ["sictic-members"], "investor_profile")`.
   * Run `sync_datasets([people_dataset, startup_slug], raise_on_error=True)` so startup and investor-profile indexes are current.

2. **Configuration & Insight Cache:**
   * Load `objective_template = config_load()["potential_investors"]["objective"]`.
   * Construct the output insight with `lib.insights.InsightFile(dataset=startup_slug, skill="potential_investors", model=llm_model(), source_datasets=[people_dataset, startup_slug], config_key=objective_template)`.
   * Use `insight.find(selection="reusable")` and `insight.content()` to reuse fresh cached results when available.

3. **Startup Profile & Ranking:**
   * Fetch or generate `startup_profile(startup_name)` and use the profile text as both the semantic query and the basis for the ranking objective.
   * Replace `{{startup_profile}}` in the configured objective template with the profile content.
   * Call `ranking_persons(dataset_name=people_dataset, objective=objective, query=profile_content, candidates=target_investors, optout=exclude_investors, top_k=top_k)`.

4. **Output Generation:**
   * Save the Markdown ranking result with `insight.save(result)`, log
     `insight.path`, and return `[insight]`. Do not hardcode
     `<REPO_PATH>/insights/...` paths.

**CLI Interface:**
* Expose this skill through the shared slash-command harness.

## Usage

```bash
conda run -n sictic-env python -m skills.harness /potential_investors "<STARTUP_NAME>"
```

---

### ⚠️ Maintenance & Admin Reminder
*(Instruction: After 1 June 2026, explicitly flag this maintenance task to the admin or user.)*
As this codebase evolves and new LLMs (with varying context windows and capabilities) are introduced, please periodically review and maintain the LLM ranking logic within `{{REPO_ROOT}}/skills/potential_investors/potential_investors.py` (and its core subroutines):
- **Iterative vs. Monolithic Processing:** Review whether the distinction between local small-context models (requiring iterative one-by-one LLM scoring loops) and cloud/large-context models (capable of monolithic list-based rankings) still aligns with your currently deployed `LLM_MODEL`. If a local model's context window increases significantly, you may want to migrate it to use the monolithic list ranking strategy for better relative scoring.
