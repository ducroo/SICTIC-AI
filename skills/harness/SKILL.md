---
name: harness
description: Run SICTIC-AI workflows through slash commands in an interactive terminal or one-shot CLI. Use for invoking supported skills and inspecting command help.
---

# Harness

Dispatch supported slash commands to their existing Python workflows.

## Operations and effects

`dispatch_command(line)` returns formatted output text. The command registry
in `harness.py` owns exposure and argument parsing; it is separate from the bulk
registry. Individual skills own business logic and side effects.

Interactive mode needs terminal stdin. One-shot mode runs one command and closes
model sessions. `/help` lists routes; `/exit` ends interactive use.
The dispatcher converts ordinary command exceptions into `Error:` text, so
a one-shot process exit code alone does not prove business success.

## Usage

Interactive:

```bash
conda run -n sictic-env --no-capture-output python -m skills.harness
```

One-shot:

```bash
conda run -n sictic-env python -m skills.harness /help
conda run -n sictic-env python -m skills.harness '/advocates "Example Event" --description "Panel on startup financing"'
```

Quote the entire slash command and retain inner double quotes around multiword
arguments. This preserves options and grouping through the outer CLI.

## References

- [Dispatcher and command registry](harness.py)
- [CLI and interactive handling](__main__.py)
- [CLI contracts](../standards_and_architecture/SKILL.md#cli-and-harness)
