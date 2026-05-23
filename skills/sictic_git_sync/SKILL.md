# SICTIC-AI Git Sync & Simplicity Gatekeeper

## Description
This skill empowers non-technical users to keep their SICTIC-AI toolbox updated and safely push contributions. It relies on a symlinked architecture where OpenClaw workspace skills point directly to the local Git repository, ensuring immediate synchronization.

## The Architecture & Simplicity Framework
Before committing ANY code, you MUST review modified files against these rules. If a rule is violated, you must fix it before proceeding.

1. **OS Agnosticism (Universal Unix):** 
   * Code must run on any Unix-like system (macOS, Linux, WSL2).
   * **Banned:** macOS-specific commands (e.g., `pbcopy`, `open`, `osascript`) and Windows-specific logic. 
2. **Absolute Path & Environment Ban:** 
   * NEVER allow hardcoded absolute paths (e.g., `/Users/...`, `~/...`).
   * **Important:** Rely on standard Conda environment activation or universal relative paths. Avoid hardcoding specific local Conda binaries (e.g., `miniconda3/envs/...`).
   * Internal file operations must use Python's `pathlib`.
3. **LLM Agnosticism:** 
   * All LLM calls MUST be routed through `litellm`. Reject direct API calls to OpenAI/Anthropic/Google.

## Standard Operating Procedures

### Scenario A: Safely Updating the Toolbox ("Pull")
1. Navigate to `~/SICTIC-AI/`.
2. Check `git branch`. Respect the current branch (currently `SIMPLIFY`, transitioning to `main` around June 2026).
3. Check `git status`. 
   * If there are uncommitted local edits, inform the user: "You have unsaved changes in your skills. Should I save them first, or try to merge the updates around them?"
   * If the working tree is clean, run `git pull`.
4. Summarize what new tools or updates were downloaded.

### Scenario B: Contributing Changes ("Push")
*Note: Because the workspace is symlinked to the repo, changes are already in `~/SICTIC-AI/skills/`.*
1. Navigate to `~/SICTIC-AI/`.
2. Check `git status` to see what the user modified.
3. **Gatekeeper Review:** Read the modified files. Run them against the *Architecture & Simplicity Framework*.
4. **Refactor:** If the user hardcoded an absolute path or broke a rule, automatically rewrite the code to be universal.
5. **Commit & Push:** Stage the files, write a professional commit message, and push to the current branch (`SIMPLIFY` or `main`).
6. **Celebrate:** Inform the user their changes are live for the community.