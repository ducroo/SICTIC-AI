---
name: expert_search
description: Rank SICTIC members for a startup's due-diligence needs using stored investor profiles and the startup profile. Use for domain, functional and strategic expertise matching.
---

# Expert search

Find members whose professional experience fits a startup's due-diligence needs.

## Inputs and outputs

The async `expert_search(startup_name, target_experts=None,
exclude_experts=None, top_k=16)` returns one Markdown ranking in
`list[InsightFile]`. Optional person filters accept names, emails or LinkedIn
IDs using the [shared ranking selection rules](../ranking/SKILL.md).

Save through `InsightFile` in the startup's insights directory as
`expert-search-<startup>-<model>.md`.

## Workflow and dependencies

Resolve the dataset through `ensure_startup_dataset`. Preserve a manual ranking
override before preparing dependencies. Otherwise request the normal
`startup_profile`, insert its content into the configured expert-search objective,
and rank stored `investor_profile` insights from `sictic-members`.
The objective prioritizes direct domain experience, then functional expertise
and strategic experience.

Direct calls require an existing member roster and investor profiles; they do
not discover or refresh members. Bulk refresh registers `startup-profile` and
`investor-profile` prerequisites; their execution follows registry scope.

Use `InsightFile.find(selection="reusable")` after reading the startup profile.
Freshness depends on indexed revisions of the startup and `sictic-members`,
plus the objective, shared ranking/structured-output configuration, supplied
startup-profile content and runtime filters/limit. A changed startup profile
invalidates the ranking even without reindexing. Edits to stored investor
profiles or the roster alone are not tracked by this cache.

## Side effects and failure behavior

Startup preparation may import or index documents and generate its profile.
Ranking reads member profiles, calls the shared ranking engine when needed,
and saves the completed report. It performs no outreach.
Input and generation failures propagate without saving a new ranking.
Missing indexed revisions prevent verified cache reuse.

## Usage

```bash
conda run -n sictic-env python -m skills.harness '/expert_search "<STARTUP_NAME>"'
```

The direct CLI accepts `--startup`, comma-separated `--include` and `--exclude`,
and `--top-k` (default 16). The harness accepts only the startup argument.

## References

- [Implementation](expert_search.py)
- [Objective](../../config/expert_search/objective.md)
- [Shared ranking contracts](../ranking/SKILL.md)
- [Insight freshness](../standards_and_architecture/SKILL.md#selection-and-freshness)
