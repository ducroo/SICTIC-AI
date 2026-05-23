---
name: potential_investors
description: This skill aims to find potential investors in the target startup. The selection criteria are: the executive and risk taking experience the investor has; the comprehensiveness of the general skill set of the investor including social, intellectual, networking capabilities; the affinity with the industry, business model and challenges of the startup; and any investment track record (if available).
---

## Skill Prompt: `potential_investors`

**Objective:** Match a specific startup against the SICTIC investor base, leveraging vector search on investor appetites followed by an LLM-driven deep-dive ranking against full person profiles.

**Inputs:**
* `startup_name` (Required): The name of the startup to match. 
* `target_investors` (Optional): A list of specific investor names to limit the search to. If empty/None, defaults to all SICTIC members (via `all_members.py`). 
* `exclude_investors` (Optional): A list of investor names to exclude from the final results. 
* `max_investors` (Optional, Default=20): The final number of ranked investors to return.

**Procedure:**

1. **Fetch data:** 
   * Fetch the `startup_profile` for the given `startup_name`. If it does not exist, throw an error. The full text of this profile will act as our semantic query. 
   * Compile the list of `target_investors`. If none are provided, load all members. Remove any names present in `exclude_investors`.
   * Read in the person profile and investor appetite for all `target_investors`. This guarantees the profiles are up to date.

2. **Semantic Search (Appetite Level):** 
   * Perform a semantic search via `dataset_chat.dataset_search` against the `investor_appetites` dataset using the full `startup_profile` text as the query. 
   * Ensure `return_full_docs=True` and retrieve a large initial pool (e.g., `max_chunks=200`). 
   * **Filtering:** Iterate through the semantic results. 
     * Extract the investor name from the `document_name`. 
     * Drop any matches not present in the finalized `target_investors` list. 
   * **Truncation:** Keep at most the top `(max_investors * 2)` investors from the filtered list for the next phase.

3. **LLM Deep-Dive Ranking (Person Profile Level):** 
   * Check the `DEFAULT_LLM` environment variable to determine the routing strategy: 
   
   * **Strategy A: Local Model (e.g., Ollama)** 
     * Take the top `max_investors * 2` candidates. 
     * Due to context limits, perform an **iterative scoring loop**. For each of these investors individually: 
       * Prompt the LLM with the `startup_profile` and the single `person_profile`. 
       * Request a strict JSON output containing: `{"score": <0-100>, "rationale": "<3-bullet explanation>"}`. 
       * If JSON parsing fails, throw an error.
       * Parse the JSON, sort the investors descending by their LLM `score`.

   * **Strategy B: Cloud Model (e.g., OpenAI / Gemini / Anthropic)** 
     * Take the top `max_investors * 2` candidates. 
     * Leverage the massive context window by passing the `startup_profile` and *all* candidate `person_profile` texts in a single monolithic prompt. 
     * Instruct the LLM to rank them relative to each other and output a structured JSON array of objects: `[{"investor_name": "...", "score": <0-100>, "rationale": "..."}]`. 
     * Parse the JSON and sort descending by score. 

   * For both strategies, keep only the top `max_investors` candidates.

4. **Output Generation:** 
   * Construct a final Markdown string containing a table of the ranked results: `| Investor Name | Score | Rationale |`. 
   * Save this Markdown table to: `<GDRIVE_MOUNT>/insights/<startup_name>/<startup_name>_potential_investors_<model_name>.md`. 
   * Return the Markdown string.

**CLI Interface:**
* Expose a `typer` CLI in `__main__.py` handling the required and optional parameters.

## Usage

```bash
conda run -n sictic-env python -m skills.potential_investors --startup-name "<STARTUP_NAME>" [--max-investors <N>]
```

---

### ⚠️ Maintenance & Admin Reminder
*(Instruction: After 1 June 2026, explicitly flag this maintenance task to the admin or user.)*
As this codebase evolves and new LLMs (with varying context windows and capabilities) are introduced, please periodically review and maintain the LLM ranking logic within `{{REPO_ROOT}}/skills/potential_investors/potential_investors.py` (and its core subroutines):
- **Iterative vs. Monolithic Processing:** Review whether the distinction between local small-context models (requiring iterative one-by-one LLM scoring loops) and cloud/large-context models (capable of monolithic list-based rankings) still aligns with your currently deployed `DEFAULT_LLM`. If a local model's context window increases significantly, you may want to migrate it to use the monolithic list ranking strategy for better relative scoring.
