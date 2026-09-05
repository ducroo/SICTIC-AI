---
name: member_preferences
description: Return the complete SICTIC member roster as Person objects with skill-specific communication preferences. Use this routine when another skill needs member opt-outs or suggestion-frequency preferences. The current implementation is a Google Sheet integration stub and assigns the standard deep-dive-invitation preference to every member.
---

# Member preferences

Call `member_preferences()` to obtain the full roster in the same `Person`
format as `persons_in_dataset`. Preferences are added lazily under the
`member_preferences` ad-hoc data namespace and keyed by the consuming skill:

```python
person.adhoc_data["member_preferences"]["deep_dive_invitation"] = "none"
```

Supported values for that preference are `none`, `fewer`, `standard`, and
`more`. Consumers decide how each value affects their workflow.

The current routine is deliberately a stub: it returns every member with
`deep_dive_invitation=standard`. Later, replace the default assignment with a
read from the ai@sictic.ch-owned Google Sheet while retaining this public API.

## Usage

```bash
conda run -n sictic-env python -m skills.harness /member_preferences
```
