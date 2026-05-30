# SICTIC-AI Git Sync & Simplicity Gatekeeper

## Description
This admin skill helps keep the SICTIC-AI toolbox updated and safely push contributions.
The installer copies `SKILL.md` instruction folders into the target workspace, while
the Python package is installed editable from the Git repository. Reinstall the skills
after changing skill instructions so external harnesses receive the updated copies.

## Workspace Model
1. **Source of truth:** The Git repository contains the Python package, scripts, tests, and canonical skill instructions.
2. **Installed skill folders:** The installer copies each skill directory into the target workspace specified by `--target`.
3. **Runtime code:** Harness commands execute the editable Python package from the Conda environment, not copied Python files from the target workspace.

## The Architecture & Simplicity Framework
Before executing a `push` action, you (the AI Agent) MUST review modified files against these rules. If a rule is violated, you must fix it before proceeding with the push.

1. **OS Agnosticism (Universal Unix):** 
   * Code must run on any Unix-like system (macOS, Linux, WSL2).
   * **Banned:** macOS-specific commands (e.g., `pbcopy`, `open`, `osascript`) and Windows-specific logic. 
2. **Absolute Path & Environment Ban:** 
   * NEVER allow hardcoded absolute paths (e.g., `/Users/...`, `~/...`).
   * Internal file operations must use Python's `pathlib`.
3. **LLM Agnosticism:** 
   * All LLM calls MUST be routed through `litellm` (via `skills.llm_chat`). Reject direct API calls to OpenAI/Anthropic/Google.

## Standard Operating Procedures

### Scenario A: Safely Updating the Toolbox
1. Run `conda run -n sictic-env python -m skills.sictic_git_sync --action pull`.
2. Re-run `./install_skills_conda.sh --target <SKILLS_TARGET> --skip-env` if skill instruction files changed.
3. Summarize the changes for the user.

### Scenario B: Contributing Changes & New Skills
1. **Status Check:** Run `conda run -n sictic-env python -m skills.sictic_git_sync --action status`.
2. **Gatekeeper Review:** If the status shows modified or new Python files, read them and ensure they adhere to the *Architecture & Simplicity Framework*. Refactor if necessary.
3. **Push:** Run `conda run -n sictic-env python -m skills.sictic_git_sync --action push --message "<professional commit message>"`.
4. Inform the user their changes are live for the community.
