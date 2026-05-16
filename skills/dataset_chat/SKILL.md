# Dataset_Chat Skill

A high-precision, multi-tenant RAG engine designed for deep document inspection and integration with llm_chat.

## Architecture

- **Qdrant (Port 6333):** Vector storage with document-level differential sync.
- **Docling (in-process):** High-fidelity document parsing with Apple Vision OCR + Ollama-backed picture descriptions. No separate service — runs in the calling Python process.
- **Ollama (Port 11434):** Dynamic embedding generation + VLM for picture descriptions.
- **Google Drive:** Source files accessed via `skills.utils.storage.get_storage()`
  — either an rclone FUSE mount (default) or the native Drive API
  (`GDRIVE_USE_API=1`). See top-level README for setup.

## Setup

The following environment variables must be present in the workspace `.env` file:
- `QDRANT_HOST`: e.g., `http://localhost:6333`
- `OLLAMA_HOST`: e.g., `http://localhost:11434`
- `GDRIVE_MOUNT` (mount mode) or `GDRIVE_USE_API=1` (API mode) — see README.
- `DEFAULT_VLM`: Used by docling (via Ollama) for picture descriptions.
- `DEFAULT_EMBEDDINGS`: Model used for vector embeddings via Ollama.

Required python packages: `qdrant-client`, `requests`, `pydantic`, `langchain-text-splitters`, `typer`.

## Usage

You can use the commands through OpenClaw or run the script directly.

### Chat with a Dataset

```bash
/home/node/miniconda3/envs/claw-env/bin/python /home/node/.openclaw/workspace-sictic-ai/skills/dataset_chat/main.py chat <DATASET_NAME> "Your question here"
```

### Delete a Dataset

```bash
/home/node/miniconda3/envs/claw-env/bin/python /home/node/.openclaw/workspace-sictic-ai/skills/dataset_chat/main.py delete <DATASET_NAME>
```

*(Note: Deleting a dataset drops the entire Qdrant collection, which will be rebuilt upon the next chat request).*
