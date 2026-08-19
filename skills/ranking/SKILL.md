---
name: ranking
description: Rank people or other supported entities against a specific objective using selected stored insights and LLM-based comparison. Use as a backend utility for workflows that need structured ranked rows or a Markdown ranking report, such as expert search or potential-investor matching.
---

# Skill: Ranking

`ranking_persons(...)` returns the human-readable Markdown report.
`rank_person_rows(...)` returns structured rows for composing other workflows
without parsing Markdown.

**Description:**
Core engine to rank entities (like SICTIC members or startup profiles) against a specific objective using an LLM-powered Swiss tournament algorithm. It ranks candidates in batches of 16 by default and acts as the unified backend for skills like `expert_search`, `potential_investors`, and `suggested_startups`.

**Available Targets:**
* `persons`: Resolves candidates and opt-outs against the canonical member roster, selects their stored profiles, and ranks them directly.

**Usage:**
`ranking` is a backend utility and is not exposed as a harness slash command.
For normal workflows, use the harness commands that call this engine:
```bash
conda run -n sictic-env python -m skills.harness /expert_search "<STARTUP_NAME>"
conda run -n sictic-env python -m skills.harness /potential_investors "<STARTUP_NAME>"
```

Run the ranking module directly only when debugging ranking behavior.
Provide an objective:
```bash
conda run -n sictic-env python -m skills.ranking --target persons --objective "Looking for someone with deep expertise in B2B SaaS sales" --top_k 8
```
