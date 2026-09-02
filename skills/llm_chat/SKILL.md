---
name: llm_chat
description: Ask the configured LLM_MODEL a question using user-provided context, questions, and answer instructions. Use when a task needs a direct LLM response over supplied context, typically context gathered from semantic search, with explicit rules or restrictions for the answer.
---

# LLM Chat Skill

A small command for testing the configured text-generation model. Runtime code
uses the infrastructure `generate_markdown` and `generate_json` interfaces.

## Setup

1. All runtime dependencies (`typer`, `python-dotenv`, `rich`, `litellm`) are installed in the `sictic-env` Conda environment by `{{REPO_ROOT}}/install.sh`.
2. The `.env` file at `{{REPO_ROOT}}/.env` must define:
   - `LLM_MODEL`: The default text-generation model to use (e.g., `gemini/gemini-1.5-pro`, `ollama/llama3`).
   - `LLM_BASE_URL`: Optional endpoint base URL. Use `http://localhost:11434` for local Ollama.
   - `LLM_API_KEY`: Optional endpoint API key. Leave blank for local Ollama.
   - `GEMINI_API_KEY`: Your Google Gemini API key.
   - `OLLAMA_HOST`: The host URL for Ollama (if using Ollama).
   - `OLLAMA_CONTEXT_LENGTH`: The baseline token context for Ollama.

## Usage

`llm_chat` is not exposed as a harness slash command. User-facing harness commands
call it internally through the shared skill APIs. Run it directly only when testing
provider configuration or debugging model behavior.

```bash
# Basic usage with default model
conda run -n sictic-env python -m skills.llm_chat "What is startup due diligence?"

```

## Features

- **Provider-neutral generation:** Uses the shared AI text-generation infrastructure
- **Ollama context management:** Sizes context between `OLLAMA_CONTEXT_LENGTH` and `OLLAMA_CONTEXT_LENGTH_MAX`
- **Rich Formatting:** Console outputs and markdown are beautifully rendered using the `Rich` library.
- **Shared recovery:** Uses the standard provider-error handling and three-attempt limit
