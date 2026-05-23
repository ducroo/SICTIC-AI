# LLM Chat Skill

A robust, production-grade CLI tool for interacting with Large Language Models (LLMs) via LiteLLM.

## Setup

1. All runtime dependencies (`typer`, `python-dotenv`, `rich`, `litellm`) are installed in `the Conda environment ` by `{{REPO_ROOT}}/install_skills.sh`.
2. The `.env` file at `{{REPO_ROOT}}/.env` must define:
   - `DEFAULT_LLM`: The default model to use (e.g., `gemini/gemini-1.5-pro`, `ollama/llama3`).
   - `GEMINI_API_KEY`: Your Google Gemini API key.
   - `OLLAMA_HOST`: The host URL for Ollama (if using Ollama).
   - `MAX_CONTEXT`: The maximum token context for Ollama before truncation occurs (e.g., `4096`).

## Usage

You can run the script directly from the CLI.

```bash
# Basic usage with default model
conda run -n sictic-env python -m skills.llm_chat "What is startup due diligence?"

# Override the default model
conda run -n sictic-env python -m skills.llm_chat "Summarize the risks." --model ollama/llama3
```

## Features

- **LiteLLM Integration:** Unified interface for hitting different providers (Gemini, Ollama, etc.).
- **Ollama Context Management:** Automatically truncates the prompt if it exceeds `MAX_CONTEXT`.
- **Rich Formatting:** Console outputs and markdown are beautifully rendered using the `Rich` library.
- **Robust Error Handling:** Catches connection errors and missing model definitions gracefully.