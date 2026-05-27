# SICTIC-AI Git Sync & Simplicity Gatekeeper

## Description
This skill empowers non-technical users to keep their SICTIC-AI toolbox updated and safely push contributions. It relies on a symlinked architecture where OpenClaw workspace skills point directly to the local Git repository, ensuring immediate synchronization.

## Automated Symlink Parity
This skill features an automated reconciliation engine that runs *before* any Git operation:
1. **Prunes dead links** in the OpenClaw workspace.
2. **Ingests raw folders** (new user-created skills) from the workspace, moves them to the Git repo, and replaces them with symlinks.
3. **Exposes new repo content** by generating missing symlinks in the workspace.

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
2. This automatically reconciles symlinks, executes the `git pull`, and reconciles again.
3. Summarize the changes for the user.

### Scenario B: Contributing Changes & New Skills
1. **Status Check:** Run `conda run -n sictic-env python -m skills.sictic_git_sync --action status`.
2. **Gatekeeper Review:** If the status shows modified or new Python files, read them and ensure they adhere to the *Architecture & Simplicity Framework*. Refactor if necessary.
3. **Push:** Run `conda run -n sictic-env python -m skills.sictic_git_sync --action push --message "<professional commit message>"`.
4. Celebrate: Inform the user their changes are live for the community.
