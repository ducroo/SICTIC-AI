# SICTIC-AI — Agent Context

## Spec Kit

This repo uses Spec Kit with Linear as the sole artifact store — no local `specs/` tree. Config: `.specify/config/linear.md`. Product project: `SICTIC-AI`. Constitution: `[CONSTITUTION] SICTIC-AI` in the shared `speckit-constitution` Linear project (label `project:sictic-ai`).

## Dual-Mode LLM Execution (Constitution Principle II)

Skills fall into two execution modes:

- **Unattended/batch** (`bulk_refresh`, `dataset_maintenance`, `linkedin_maintenance`, `gdrive_sync`, cron jobs): routed through `litellm` per `LLM_MODEL`/`VLM_MODEL`/`EMBEDDING_MODEL`. Unchanged, untouched by agent-orchestrated work.
- **Agent-orchestrated** (on-demand skills, first implemented for `dd_checks_agent` / `startup_profile_agent`, feature `001-agent-orchestrated-dd`): executed by a live Claude Code agent session (including subagents via the `Agent` tool) reading dataset files directly via `Read`/`Grep`, instead of a headless script calling `litellm.completion()`. No `LLM_API_KEY` or local text-generation model required. Embeddings/Qdrant stay on the litellm/Ollama path regardless of mode — Claude has no embedding endpoint.

Agent-orchestrated skill output still persists through the unmodified `lib.insights.file.InsightFile` mechanism, using `model="anthropic/claude-code-agent"` so filenames get a distinct `claude-code-agent` suffix and never collide with litellm-generated insights of the same skill/dataset. See Linear `LE3-271` (RESEARCH) for the full rationale.

Every LLM-dependent skill's `SKILL.md` must state which mode it uses — see `skills/standards_and_architecture/SKILL.md` (its blanket "litellm only" clause predates this principle and is flagged for a follow-up update, not yet applied).
