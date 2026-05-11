# LLM Chat Skill

A robust, production-grade CLI tool for interacting with Large Language Models (LLMs) via LiteLLM.

## Setup

1. Make sure you have the required dependencies installed:
   `pip install typer python-dotenv rich litellm`
2. Create a `.env` file in the root of your workspace (or where you run the tool) with the following variables:
   - `DEFAULT_LLM`: The default model to use (e.g., `gemini/gemini-1.5-pro`, `ollama/llama3`).
   - `GEMINI_API_KEY`: Your Google Gemini API key.
   - `OLLAMA_HOST`: The host URL for Ollama (if using Ollama).
   - `MAX_CONTEXT`: The maximum token context for Ollama before truncation occurs (e.g., `4096`).

## Usage

You can run the script directly from the CLI.

```bash
# Basic usage with default model
/home/node/miniconda3/bin/conda run -n claw-env python scripts/llm_chat.py "What is startup due diligence?"

# Override the default model
/home/node/miniconda3/bin/conda run -n claw-env python scripts/llm_chat.py "Summarize the risks." --model ollama/llama3
```

## Features

- **LiteLLM Integration:** Unified interface for hitting different providers (Gemini, Ollama, etc.).
- **Ollama Context Management:** Automatically truncates the prompt if it exceeds `MAX_CONTEXT`.
- **Rich Formatting:** Console outputs and markdown are beautifully rendered using the `Rich` library.
- **Robust Error Handling:** Catches connection errors and missing model definitions gracefully.