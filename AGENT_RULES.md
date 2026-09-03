# Rules of the game — for AI coding agents

> Named `AGENT_RULES.md` rather than `AGENTS.md` on purpose: `AGENTS.md` is in
> this repository's `.gitignore`, alongside the other per-machine agent files,
> so anything written there is never committed.

**Paste this to your coding agent before it writes anything, every session.**

You are contributing to SICTIC-AI, a shared codebase with about ten
contributors and a working production system behind it. Most of what you are
asked to build already exists in some form. Your job is to find it and compose
it, not to write it again.

## Before you write a single line

1. **Work from current `main`.** `git fetch origin && git merge origin/main`.
   A stale checkout is the single most reliable way to reinvent something: the
   routine you are about to write may have been added last week.
2. **Read `skills/standards_and_architecture/SKILL.md` in full.** It is the
   binding description of how this repository is laid out and how code is
   written here. It is not background reading.
3. **Look for what already exists.** `ls skills/` lists twenty-five
   capabilities. `ls lib/` lists the shared infrastructure. Search before
   building: `grep -rn "def <the-thing-you-want>" lib skills`.
4. **Verify every name against the source.** If a document, a table, or a
   colleague tells you a routine exists, open the file and confirm the
   signature. Names move. A reuse list is only as good as the tree it was
   checked against.

## What you must not do

* **Do not create a second way to do something that already has one.** One
  checklist format, one checklist parser, one person model, one path resolver,
  one way to store generated output. If the existing one does not fit, say so
  and ask — do not fork it.
* **Do not modify existing code to make your feature fit.** Add alongside it.
  Propose the refactor separately, in writing, and let a human decide.
* **Do not hardcode.** No prompts in Python, no model names, no storage paths,
  no magic thresholds. Prompts and settings live in `config/`; paths come from
  `lib.datasets.paths`; the model comes from `lib.model_config.llm_model`.
* **Do not print.** Use `lib.logger.get_logger`. `print()` is reserved for final
  output to the user.
* **Do not weaken a check to get green.** Not a test, not a linter, not a
  gate. If a check fails, the check is usually right.
* **Do not claim it works because it compiles or because tests pass.** Run it
  against real data and read the output.

## The routines you are most likely to need

Confirm each one against the source before using it.

| you need to… | use |
|---|---|
| resolve a startup name | `lib.startups.identity.canonical_startup_slug` |
| get a startup's dossier ready | `lib.startups.sources.ensure_startup_dataset`, then `lib.datasets.ingestion.sync_datasets` |
| find where data lives | `lib.datasets.paths` — never build a path by hand |
| ask a question of a dossier | `skills.dataset_chat.dataset_chat.dataset_chat` |
| run a checklist over a dossier | `skills.batch_audit.batch_audit.batch_audit` |
| parse a checklist | `skills.batch_audit.checklist.parse_checklist` — the only checklist parser |
| render an audit as a table | `skills.batch_audit.rendering.json_to_markdown_table` |
| force structured output from a model | `lib.structured_output` |
| one free-form model call | `skills.llm_chat.llm_chat.llm_chat` |
| save generated output | `lib.insights.InsightFile` — handles paths, model tags, caching, freshness |
| represent a person | `lib.people.model.Person` — do not introduce another |
| find people in a dossier | `lib.people.discovery.persons_in_dataset` |
| resolve a LinkedIn profile | `lib.linkedin.LinkedInResolver` |
| load prompts and settings | `skills.config_load.config_load.config_load` |
| build a CLI | `lib.cli.run_command` + Typer, in a `__main__.py` with no logic in it |

## The shape of a skill

```text
skills/<skill_name>/
├── SKILL.md          what it does and how to invoke it - mandatory
├── __init__.py
├── __main__.py       Typer CLI. Zero business logic.
├── <skill_name>.py   the main function, named exactly like the skill
├── core/             (optional) heavy lifting
└── utils/            (optional) helpers unique to this skill
```

The main function returns a flat `list[InsightFile]`, including when the result
came from cache. If it takes a dataset, that is its first parameter.

## When you finish

* Tests for what you added, run and passing.
* `SKILL.md` written for any new skill.
* A short note of anything you wanted to change but did not — that list is more
  valuable than a silent workaround.
* Say plainly what you did **not** verify. "I did not run this against a real
  startup" is useful. "Implemented successfully" is not.
