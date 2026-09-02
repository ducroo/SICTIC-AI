---
name: advocates
description: Shortlists 10 members that can represent SICTIC at an event; ranging from pitch marathons, panel discussions to podium presentations. Based on event description and required skills provided by the user.
---

The output Insight's `config_cache_key()` covers the advocates objective, both shared
ranking config sections, the event description, and runtime ranking options.
The shared ranking engine constrains permitted profile IDs with JSON Schemas,
supplies them to LiteLLM, repairs the response, and validates it locally.

## Usage

Via the slash-command harness:

```bash
conda run -n sictic-env python -m skills.harness /advocates "<EVENT_NAME>" --description "<EVENT_DESCRIPTION>"
```

Via the direct Typer entrypoint:

```bash
conda run -n sictic-env python -m skills.advocates --event "<EVENT_NAME>" --description "<EVENT_DESCRIPTION>"
```
