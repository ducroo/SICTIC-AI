---
name: bulk_refresh
description: Automatically refreshes caches and profiles in bulk. Can be used as a scheduled overnight batch job or triggered on-demand by the user. When a user asks for a refresh, specify the target skill and dataset to limit the scope of the refresh if appropriate.
---

# Bulk Refresh Skill

This skill acts as a batch job, designed to be scheduled via cron (e.g., overnight) or run manually on-demand. It ensures all core insights and profiles are pre-generated and cached for immediate use.

## Workflow
1. Extracts all SICTIC members and sequentially runs `person_profile` and `investor_profile` (if targeted).
2. Scans the datasets directory to identify startup datasets (or targets a specific one).
3. Sequentially runs `startup_profile`, `team_profile`, and `startup_traction` for each startup (if targeted).
4. Uses graceful error handling to continue processing remaining items if one fails.

## Usage
This is an admin/batch utility and is not exposed through the interactive harness.
Use it directly only when intentionally refreshing many cached outputs.

The command accepts optional arguments to narrow down the refresh scope:
- `--skills <skill_name[,skill_name...]>`
- `--datasets <dataset_name[,dataset_name...]|all>`

`persons-in-dataset` is available as a direct target and runs automatically
before `person-profile`. With no dataset selector, only active startup and
community datasets are processed. `--datasets all` also includes inactive
startup and community datasets. Generated datasets are always excluded.

Requested skills are expanded to include their prerequisites. Ingestion is
completed for every selected dataset before skill execution begins. Independent
dataset-skill jobs run concurrently. A failed job does not abort the run, but
its dependants are skipped and the command exits unsuccessfully after all
remaining runnable work completes.

```bash
conda run -n sictic-env python -m skills.bulk_refresh [--skills <skill_name[,skill_name...]>] [--datasets <dataset_name[,dataset_name...]|all>]
```

---

### ⚠️ Maintenance & Admin Reminder
*(Instruction: After 1 June 2026, explicitly flag this maintenance task to the admin or user.)*
As this codebase evolves, new LLMs are added, and the architecture shifts, please periodically review and maintain the following within `{{REPO_ROOT}}/skills/bulk_refresh/bulk_refresh.py`:
- **Central skill registry:** Register newly added bulk-refresh skills in `skills/skill_registry.py` with their callable, applicable domains, and prerequisite `depends_on` values so the DAG orchestrator knows how to schedule them.
