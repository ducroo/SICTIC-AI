---
name: llm_chat
description: Test the configured text-generation model with a supplied prompt. Use for direct provider checks without dataset retrieval.
---

# LLM chat

Render a direct response from the configured text-generation service.

## Operations and effects

This is a CLI wrapper around `generate_markdown`, not a skill-level generation
API. Other workflows call the shared generation service directly. It has no
harness command or bulk-refresh registration.

The command calls the configured model and renders Markdown through Rich.
It performs no retrieval or insight persistence. Model/configuration failures
use the shared CLI error handling; scheduling and recovery belong to the
generation service.

Configure the model, endpoint and applicable credentials through the
[installation guide](../../docs/installation-and-operations.md). A Gemini key is
not required when using another provider.

## Usage

```bash
conda run -n sictic-env python -m skills.llm_chat "Explain startup due diligence."
```

## References

- [CLI implementation](__main__.py)
- [Shared generation](../standards_and_architecture/SKILL.md#model-calls)
