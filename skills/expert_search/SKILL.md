---
name: expert_search
description: A specialized matchmaker designed to connect startups with the most qualified members of the community for due diligence, evaluation, investment, or mentorship. It generates a ranked, evidence-based list of experts from the `person_profile` dataset based on a deep analysis of a startup's industry, technology stack, and business model.
---

The output Insight's `config_cache_key()` covers the expert-search objective, both
shared ranking config sections, and runtime target, exclusion, and `top_k`
options. The ranking engine constrains permitted profile IDs with JSON Schemas,
supplies those schemas to LiteLLM, repairs the response, and validates it
locally before rendering Markdown.

## Usage

```bash
conda run -n sictic-env python -m skills.harness /expert_search "<STARTUP_NAME>"
```
