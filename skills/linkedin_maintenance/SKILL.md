---
name: linkedin_maintenance
description: List, import, and diagnose manually scraped LinkedIn profiles.
---

# LinkedIn Maintenance

LinkedIn profile resolution is implemented in `lib.people.linkedin`. This skill owns
the human-in-the-loop scraping workflow.

```bash
python -m skills.linkedin_maintenance missing
python -m skills.linkedin_maintenance import profiles.json
python -m skills.linkedin_maintenance import profiles.json --dataset sictic-members
python -m skills.linkedin_maintenance diagnose
```
