# Skill: Ranking

**Description:**
Core engine to rank entities (like SICTIC members) against a specific objective using an LLM-powered Swiss tournament algorithm. It acts as the unified backend for skills like `expert_search` and `potential_investors`.

**Available Targets:**
* `persons`: Resolves member profiles, runs a semantic search to filter candidates, and ranks them.

**Usage:**
`ranking` is a backend utility and is not exposed as a harness slash command.
For normal workflows, use the harness commands that call this engine:
```bash
conda run -n sictic-env python -m skills.harness /expert_search "<STARTUP_NAME>"
conda run -n sictic-env python -m skills.harness /potential_investors "<STARTUP_NAME>"
```

Run the ranking module directly only when debugging ranking behavior.
Provide an objective and optionally a semantic query:
```bash
conda run -n sictic-env python -m skills.ranking --target persons --objective "Looking for someone with deep expertise in B2B SaaS sales" --query "B2B SaaS Sales" --top_k 8
```
