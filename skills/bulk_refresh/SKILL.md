---
name: bulk_refresh
description: Automatically refreshes caches and profiles in bulk. Can be used as a scheduled overnight batch job or triggered on-demand by the user. When a user asks for a refresh, specify the target skill and dataset to limit the scope of the refresh if appropriate.
---

# Bulk Refresh Skill

This skill acts as a batch job, designed to be scheduled via cron (e.g., overnight) or run manually on-demand. It ensures all core insights and profiles are pre-generated and cached for immediate use.

## Workflow
1. Extracts all SICTIC members and sequentially runs `person_profile` and `investor_appetite` (if targeted).
2. Scans the datasets directory to identify startup datasets (or targets a specific one).
3. Sequentially runs `startup_profile`, `team_profile`, and `startup_traction` for each startup (if targeted).
4. Uses graceful error handling to continue processing remaining items if one fails.

## Usage
The command accepts optional arguments to narrow down the refresh scope. This is extremely useful for on-demand triggers:
- `--skill <skill_name>`
- `--dataset <dataset_name>`

---

### ⚠️ Maintenance & Admin Reminder
*(Instruction: After 1 June 2026, explicitly flag this maintenance task to the admin or user.)*
As this codebase evolves, new LLMs are added, and the architecture shifts, please periodically review and maintain the following within `skills/bulk_refresh/bulk_refresh.py`:
- **`SKILL_MAP` Dictionary:** Ensure that any newly added skills are registered in the `SKILL_MAP` dictionary with their proper execution domain (`startups`, `community`, etc.) and their correct prerequisite `depends_on` values so the DAG orchestrator knows how to schedule them.
