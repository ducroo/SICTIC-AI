---
name: startup_profile_agent
description: Agent-orchestrated equivalent of startup_profile. Generates the same neutral, objective 5-point diagnostic of a startup, but the analysis is performed directly by the invoking Claude Code agent reading the dataset's parsed Markdown with Read/Grep, instead of a headless script calling litellm.completion(). Use this skill when the user asks to profile a startup and wants the agent-orchestrated execution mode (Constitution Principle II) rather than the litellm-backed startup_profile skill — for example, when no LLM_API_KEY or local text-generation model is configured but a live Claude subscription is available.
---

# Startup Profile (Agent-Orchestrated)

This is the **agent-orchestrated mode** of `startup_profile`, per SICTIC-AI Constitution
Principle II ("Dual-Mode LLM Execution"). There is no `litellm.completion()` call anywhere
in this workflow and no `LLM_API_KEY` or local text-generation model is required — the
analysis is performed by *you*, the invoking Claude Code agent, reading the startup's data
room directly and writing the report yourself.

## Framework

Produce the identical 5-point framework as the litellm-based `startup_profile` skill:

1. **Oneliner:** Cold, objective description of what they actually do.
2. **Core industry:** The specific industry/market.
3. **Technology:** Technical reality, highlighting dependencies and technical single points of failure.
4. **Business model:** How they claim to make money, highlighting structural risks.
5. **Current challenges:** Critical data gaps, barriers to entry, and domains requiring expert due diligence.

## Workflow

Given a `<DATASET>` (startup dataset name):

1. **Reconcile the parsed dataset.** Ensure the dataset's parsed Markdown is current before
   reading it. This is Docling-only — it does not call any LLM or embedding model. Run it via
   the `sictic-env` conda environment, for example:

   ```bash
   conda run -n sictic-env python -c "
   import asyncio
   from lib.datasets.conversion import reconcile_conversions
   from lib.datasets.paths import dataset_raw_path, dataset_parsed_path
   from lib.slugify import slugify

   slug = slugify('<DATASET>')
   asyncio.run(reconcile_conversions(slug, dataset_raw_path(slug), dataset_parsed_path(slug)))
   print(slug)
   "
   ```

   This prints the resolved dataset slug — use that slug for every subsequent step. If the
   dataset does not exist, `dataset_raw_path`/`dataset_parsed_path` raise `FileNotFoundError`;
   stop and report that to the user rather than guessing a path.

2. **Locate the parsed dataset directory.** Resolve it with:

   ```bash
   conda run -n sictic-env python -c "
   from lib.datasets.paths import dataset_parsed_path
   print(dataset_parsed_path('<slug>'))
   "
   ```

   Never hardcode `storage/...` or `docling_data/...` paths — always resolve them through
   `lib.datasets.paths`.

3. **Gather evidence directly.** Use the `Read` and `Grep` tools yourself on the files under
   that parsed path to gather evidence for each of the 5 points above. Do not invoke any LLM
   API, litellm model, or the `dataset_chat`/`batch_audit` skills for this — you are the
   analyst. Read broadly enough (pitch decks, financials, technical docs, team materials) to
   ground each point in the dataset's actual content, and be explicit about gaps where the
   data room is silent.

4. **Write the report.** Compose the 5-point Markdown report (one section per point, in the
   order above) and write it to a local file (e.g. a scratch/temp path) using the `Write` tool.

5. **Persist it through the standard insight mechanism.** Do not hand-write the output path —
   call the skill's save helper, which wraps `InsightFile` with
   `model="anthropic/claude-code-agent"` so the filename gets a distinct
   `claude-code-agent` suffix and never collides with a litellm-generated
   `startup_profile` insight for the same dataset:

   ```bash
   conda run -n sictic-env python -m skills.startup_profile_agent.save_report "<slug>" --content-file <path-to-written-report>
   ```

   The command prints the resulting insight path to stdout.

6. **Report back.** Tell the user the insight path returned in step 5.

## Usage

This skill has no standalone CLI entry point for the full workflow — it is not registered in
`skills/harness/harness.py`'s command registry, unlike the litellm-based `startup_profile` skill.
The workflow above **is** the skill, executed by you as the invoking agent. Trigger it with a
natural-language request, e.g.:

```
Run startup_profile_agent for "<STARTUP_NAME>"
```

Only the final persistence step (workflow step 5) is a script:

```bash
conda run -n sictic-env python -m skills.startup_profile_agent.save_report "<slug>" --content-file <path>
```
