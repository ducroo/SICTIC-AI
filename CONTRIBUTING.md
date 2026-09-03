# Contributing to SICTIC-AI

This repository is worked on by about ten people, several of them using AI
coding agents, and it runs a live system. This page is what a new contributor
reads first.

If you are directing an AI agent, give it **`AGENT_RULES.md`** as well. It is the
same rules, written for the agent rather than for you.

---

## Before you start

**1. Agree what you are building, with a person.** Open an issue describing the
problem before writing a solution. Most wasted work here is not badly written —
it is a duplicate, or the wrong shape, and both are cheap to catch in a
paragraph and expensive to catch in a diff.

**2. Check whether it already exists.** Twenty-five skills and a shared `lib/`
already cover a lot:

```bash
ls skills/        # the capabilities that exist
ls lib/           # the shared infrastructure
grep -rn "def <the-thing-you-want>" lib skills
```

**3. Read `skills/standards_and_architecture/SKILL.md`.** It is the binding
description of the layout and the coding rules. Everything below assumes it.

**4. Start from current `main`.** Not from your checkout of three weeks ago.
This is the most common cause of accidentally rewriting something that already
exists.

---

## How work should be shaped

**Additive first.** A new capability is a new skill package. It composes what is
already in `lib/` and `skills/`, and changes nothing existing. If your feature
seems to need an existing routine changed, that is a separate conversation and a
separate pull request — write the reasons down and let a human decide.

**One way to do each thing.** One checklist format and one parser. One person
model. One path resolver. One way to store generated output. If the existing one
does not fit your case, say so before working around it. A second way to do
something costs everyone, permanently.

**Nothing hardcoded.** Prompts, instructions and thresholds live in `config/`
and are loaded with `config_load()`. Paths come from `lib.datasets.paths`. The
model comes from `lib.model_config.llm_model`. If you are typing a prompt into a
`.py` file, stop.

**Small pull requests.** One reviewable change. A large PR does not get reviewed
carefully — it gets approved.

---

## What a pull request must contain

* **Tests that run.** There are ninety test files in `tests/`; add to them.
* **A `SKILL.md`** for any new skill — what it does, how it works, how to
  invoke it.
* **A description that says what you did not verify.** "Not yet run against a
  real startup dossier" is a useful sentence, not an admission of failure.
* **Green checks.** Never disable, skip or weaken a check to get there.

---

## Where things are stored

Nothing generated goes in the repository. It goes to configured storage.

| what | where |
|---|---|
| prompts, instructions, checklists, schemas | `config/<skill>/` |
| raw startup and community data | the `startups` / `community` storage domains |
| generated reports and profiles | `insights`, always through `lib.insights.InsightFile` |
| disposable cache | `cache/` — never anything you would miss |

`InsightFile` handles naming, the model tag, freshness and reuse. Do not write
files yourself and do not construct paths by hand.

---

## How to document

* **`SKILL.md`** — mandatory for every skill, and the first thing anyone reads.
* **The main function's docstring** — one paragraph, plain language, describing
  what the skill produces. It is what a person sees when they list skills.
* **Comments** — explain *why*, not *what*. The code already says what.
* **Leave a wishlist.** Anything you wanted to change but deliberately did not.
  This is how the repository learns where it hurts.

---

## Working with AI agents

Agents are already contributing here. They are fast and they are good until they
are asked to reuse something — at which point, unprompted, they will confidently
rewrite it.

* Give the agent **`AGENT_RULES.md`** at the start of every session.
* Make it show you which existing routines it used, **by file and function
  name**, and check one or two.
* Treat "successfully implemented" as an unverified claim. Ask what it ran, and
  what it did not.
* An agent's tests passing is not evidence the feature works. It is evidence
  the tests pass.

---

## The two failures that hurt most

**A stale checkout.** Six shared components were added to this repository in a
single recent stretch. A contributor working from an old copy would not have
seen them and would have written four of them again — while following a brief
whose whole purpose was to prevent that.

**A silent rewrite.** Building a second parser, a second person model, or a
second way to store output does not break anything on the day. It breaks the
next person, and the one after that, and it is never worth the time it saved.
