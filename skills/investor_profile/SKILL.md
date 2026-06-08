---
name: investor_profile
description: Builds investor profiles by appending manual investment track records and preferences to generated person profiles.
---

# Investor Profile

This deterministic bulk skill combines every generated person profile with the
matching manually maintained investment track record.

For the default `sictic-members` source dataset:

```text
Person profile:
storage/community/sictic-members/insights/person-profile/<linkedin-id>-<model>.md

Track record:
storage/community/sictic-members/datasets/track-record/<linkedin-id>.md

Investor profile:
storage/community/sictic-members/insights/investor-profile/<linkedin-id>-<model>.md
```

Every person-profile model variant is retained. Missing track records are
represented by an explicit note. The skill does not call an LLM.

## Usage

```bash
conda run -n sictic-env python -m skills.investor_profile
conda run -n sictic-env python -m skills.investor_profile --source-dataset another-community
```
