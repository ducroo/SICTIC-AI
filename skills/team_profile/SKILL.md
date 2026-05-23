---
name: team_profile
description: Performs deep-dive due diligence on a startup's leadership. Identifies founders, reconciles resumes with LinkedIn, and flags legal/background documents.
---

# Team Profiling Skill

This skill executes a multi-stage reconnaissance and evaluation pipeline for a given startup.

## Workflow

1. **Discovery (Broad & Deep):** 
 - **Web:** Executes a Google search to map the entire headcount via LinkedIn, i.e., `site:linkedin.com/in/ <STARTUP_NAME> -intitle:jobs -intitle:directories`.
 - **Dataset:** If the startup is in a dataset, uses `dataset_chat` to locate "Founder," "CXO," "Management," or "Team" folders. Specifically looks for resumes/CVs, certificates & academic records, and legal background checks (e.g., "Auszug Strafregister", "Criminal Record").

2. **Identity Resolution:** 
 - Filters all discovered names into two buckets: **Founders/CXOs** (to be profiled) and **Other Employees** (to be listed).
 - "CXO" logic: Captures any C-level role (CEO, CTO, COO, CMO, CFO, etc.).

3. **Data Reconciliation:** 
 - Scrapes LinkedIn via Apify for the Founder bucket (`client.actor("dev_fusion/Linkedin-Profile-Scraper")`).
 - Strips unnecessary links and caches JSONs in `datasets/<STARTUP_NAME>/linkedin`.
 - Compares LinkedIn data against Data Room resumes, treating LinkedIn as the source of truth for dates and titles; discrepancies are flagged as "Integrity/Flexibility" notes.

4. **Output Generation:** 
 - **Section A:** Full Employee List (Name + LinkedIn URL).
 - **Section B:** Individual Founder Assessments (Table).
 - **Section C:** Team Effectiveness & Synergy Report.
 - Saved to `insights/<STARTUP_NAME>/<STARTUP_NAME>_team_profile_<MODEL_NAME>.md`.

## Usage

```bash
conda run -n sictic-env python -m skills.team_profile --startup "<STARTUP_NAME>"
```