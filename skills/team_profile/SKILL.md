---
name: team_profile
description: Performs deep-dive due diligence on a startup's leadership. Identifies founders, reconciles resumes with LinkedIn, and flags legal/background documents.
---

# Team Profiling Skill

This skill executes a multi-stage reconnaissance and evaluation pipeline for a given startup.

## Workflow

1. **Dataset Preparation:**
   * Convert `startup_name` to a dataset slug with `slugify(...)`.
   * Resolve and prepare the startup dataset with `ensure_startup_dataset(...)`.
   * Run `sync_datasets([dataset_slug], raise_on_error=True)` so parsed Markdown and Qdrant are current before analysis.

2. **Configuration & Insight Cache:**
   * Load `resume_queries`, `team_assessment_prompt`, and optional `linkedin_classification_prompt` from `config_load()["team_profile"]`.
   * Build an output insight with `lib.insights.InsightFile(dataset=dataset_slug, skill="team_profile", model=llm_model(), prompt_key=<resume_queries_and_prompts>)`.
   * Use `insight.find_reusable()` and `insight.content()` to reuse a fresh existing team profile when available.

3. **Person Discovery & Profile Reuse:**
   * Call `person_profile(startup_name, names=None)` to discover and synthesize profiles for the startup's associated people.
   * `person_profile` handles LinkedIn resolution, cached LinkedIn payloads, data-room mentions, personal documents, and generated person-profile insights.

4. **Team Context Assembly:**
   * Run `dataset_search(dataset_name=dataset_slug, query=resume_queries)` to collect broader resume/CV/team-document chunks.
   * Deduplicate all person-profile mentions and resume-query chunks by `chunk_id`.
   * Build a single context containing aggregated data-room mentions and discovered person profile summaries.

5. **LLM Assessment & Output:**
   * Call `llm_chat(prompt=<assembled_context_and_team_profile_instructions>)`.
   * Save the Markdown report with `insight.save(report_md)`, log
     `insight.path`, and return `[insight]`.

## Usage

```bash
conda run -n sictic-env python -m skills.harness /team_profile "<STARTUP_NAME>"
```
