---
name: dataset_chat
description: Answer questions from a named startup or community dataset using retrieved evidence. Use for grounded Markdown or structured JSON; retrieval can synchronize and write dataset state.
---

# Dataset chat

Retrieve dataset evidence and pass it to the shared text-generation service.

## Inputs and outputs

The async `dataset_chat(dataset_name, queries, prompt, ...)` returns Markdown,
not an insight artifact. Queries accept a string or list; `max_chunks=25` and
`strict_insufficient_context=True` are defaults.

`dataset_chat_json(..., schema, reviewer=None, ...)` is the structured adapter,
returning a dictionary/list or `None`. It uses shared schema validation and
review. Both accept a `cacheable_prompt_prefix`.

## Workflow and dependencies

Search through `lib.datasets.search.dataset_search(..., raise_on_error=True)`,
render chunks with source/page metadata, limit supplied context to the character
budget, and call `generate_markdown` or `generate_json`.
An oversized first chunk can be truncated. Context budgeting currently uses
`OLLAMA_CONTEXT_LENGTH_MAX`, including for other configured providers.

Use the shared [installation guide](../../docs/installation-and-operations.md)
for setup. Parsing is in-process Docling; storage is local and generation/embedding
endpoints are configurable. This skill does not depend on the `llm_chat` CLI.

## Side effects and failure behavior

Search may convert and index documents. The skill saves no report and manages
no completed-answer cache. Provider and retrieval failures propagate.

Empty queries/prompts or zero hits normally skip generation. Markdown returns
the configured fallback marker; JSON returns `None`. Disabling strict Markdown
grounding changes the prompt, not the zero-hit behavior.

The JSON adapter's existing `allow_empty_retrieval=True` permits zero-hit
generation when a nonempty shared prefix is supplied. Batch audit uses this
path for every check. Citation truth and grounding are prompt requirements,
not established by schema validation.

## Usage

```bash
conda run -n sictic-env python -m skills.harness '/dataset_chat "<DATASET>" "What evidence supports revenue?"'
conda run -n sictic-env python -m skills.harness '/sync "<DATASET>"'
```

The direct CLI has `search`, `chat` and `sync` commands. Its retained
`sync --force` flag does not force reprocessing in the current ingestion API.
Direct search uses the search API's default error policy; generated answers
use strict retrieval errors.

## References

- [Implementation](dataset_chat.py), [direct CLI](__main__.py)
- [Retrieval and synchronization](../standards_and_architecture/SKILL.md#search-and-evidence)
- [Generation contracts](../standards_and_architecture/SKILL.md#model-calls)
