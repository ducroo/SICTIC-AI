---
name: suggested_startups
description: Rank a provided list of startups against a list of investors by matching startup value propositions with investor professional backgrounds and interests.
---

## Skill Prompt: `suggested_startups`

**Objective:** Rank a provided list of startups against a list of investors by matching startup value propositions with investor professional backgrounds and interests.

**Inputs:**

* `startups`: A list of startup names (e.g., `["avientus", "fabas"]`). 
* `investors`: A list of investor names (e.g., `["Lucas du Croo de Jongh", "John Doe"]`).

**Procedure:**

1. **Startup Profiling:** 
 
 * For every startup in the input list, execute `startup_profile(<STARTUP_NAME>)`. 
 * Capture the resulting 5-bullet point Markdown string (the first element of the returned tuple).

 

2. **Investor Loop:** For each name in the `investors` list: 
 
 * **Data Retrieval:** Use `LinkedInResolver` for the `sictic-members` dataset when cached LinkedIn identities are required. General storage remains local; Google Drive synchronization is handled separately.
 * **Self-Correction (Fallback):** Check the returned JSON. If the profile is sparse, empty, or missing entirely, inject a hardcoded **"General Interest"** fallback string (e.g., *"No detailed profile available. Assume General Interest in broad tech trends and standard investment criteria."*) as their profile data.

 

3. **Ranking Logic:** 
 
 * For each investor, call the `llm_chat()` utility. 
 * **Context Provided:** Inject the prompt found dynamically via `config_load()` at `conf['suggested_startups']['suggested_startups_prompt']`. Pass the investor’s retrieved LinkedIn profile (or fallback string) and the full compiled list of startup profiles with the startup\_name added on top of each. All profiles should be clearly separated 
 * **Output Format:** Instruct the LLM to return a strict **JSON object** containing: 
 * `startup_name` 
 * `rank` (1 to N) 
 * `rationale` (A brief explanation of why this is a fit).

 

4. **Data Assembly:** Aggregate the parsed JSON results into a Markdown table with the following structure: 
 
 | Investor Name | Suggested Startups | Rank | Rationale | 
 
 | :--- | :--- | :--- | :--- | 
 
5. **Output Generation:** Save the final Markdown table to the following path: `<REPO_PATH>/insights/sictic_members/suggested_startups_<model_name>.md`

## Usage

```bash
conda run -n sictic-env python -m skills.harness /suggested_startups --startups "<startup1>,<startup2>" --investors "<name1>,<name2>"
```
