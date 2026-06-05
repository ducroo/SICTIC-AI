# Dataset_Chat Skill

A high-precision, multi-tenant RAG engine designed for deep document inspection and integration with llm_chat.

## Architecture

- **Qdrant (Port 6333):** Vector storage with document-level differential sync.
- **Docling-Serve (Port 5001):** High-fidelity document parsing with VLM support.
- **Ollama (Port 11434):** Dynamic embedding generation.
- **Rclone-Mount (Port 5572):** Real-time remote file monitoring via the RC API.

## Setup

The following environment variables must be present in the repo's `.env` file (`{{REPO_ROOT}}/.env`):
- `QDRANT_HOST`: e.g., `http://localhost:6333`
- `DOCLING_HOST`: e.g., `http://localhost:5001`
- `OLLAMA_HOST`: e.g., `http://localhost:11434`
- `RCLONE_HOST`: e.g., `http://localhost:5572`
- `VLM_MODEL`: Used by Docling-Serve/Ollama for image-to-text generation.
- `EMBEDDING_MODEL`: Model used for vector embeddings.
- `EMBEDDING_BASE_URL`: Optional endpoint base URL. Use `http://localhost:11434` for local Ollama.
- `EMBEDDING_API_KEY`: Optional endpoint API key. Leave blank for local Ollama.

Required python packages (installed into `the Conda environment ` by `install_skills.sh`): `qdrant-client`, `requests`, `pydantic`, `langchain-text-splitters`, `typer`.

## Usage

Use the commands through the shared harness.

### Chat with a Dataset

```bash
conda run -n sictic-env python -m skills.harness /dataset_chat <DATASET_NAME> "Your question here"
```

### Sync a Dataset

```bash
conda run -n sictic-env python -m skills.harness /sync <DATASET_NAME>
```

Dataset deletion is intentionally not exposed through the harness.
