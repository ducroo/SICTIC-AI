# SICTIC-AI

A collection of Python skills (LLM-powered analysis routines for startups, investors, and due-diligence work) backed by local services: Qdrant (vector DB), Ollama (LLM inference), Docling (document parsing), and rclone (Google Drive mount).

## Runtime context

This directory is part of an **openclaw** runtime system — the skills are normally invoked from the openclaw harness via the containerized stack in `docker-compose.yml`. The skills themselves are pure Python and have no hard dependency on openclaw; they could be wired into other harnesses (Claude Code subagents, a CLI runner, an MCP server, etc.) as long as the required env vars and backing services are reachable.

## Environment setup (conda)

The canonical Python environment is defined in `environment.yml` (env name: `sictic-env`, Python 3.12).

```bash
conda env create -f environment.yml
conda activate sictic-env
```

The skills package expects to be importable as `skills.*`. Either run from the repo root or set `PYTHONPATH`:

```bash
export PYTHONPATH="$(pwd)"
```

### Configuration: `.env`

Copy the template and fill in values:

```bash
cp .env-template .env
```

Required variables (the four `*_HOST` vars are not in the template yet — add them manually):

| Variable | Purpose | Example |
|---|---|---|
| `GDRIVE_MOUNT` | Local path to the rclone/Google Drive mount | `/data` or `~/gdrive` |
| `WORKSPACE_DIR` | Path to this repo on the host | `/Users/you/.openclaw/workspace-ops/SICTIC-AI` |
| `DEFAULT_LLM`, `DEFAULT_VLM`, `DEFAULT_EMBEDDINGS` | litellm-style model names | `ollama/qwen3.5:9b` |
| `OLLAMA_MAX_CONTEXT`, `OLLAMA_CONTEXT_LENGTH` | Context window sizing | `32768` / `16384` |
| `RANKED_LLMS` | Preferred LLM fallback order (CSV) | see `.env-template` |
| `MAX_CONCURRENT_EMBEDS`, `MAX_CONCURRENT_LLMS`, `MAX_CONCURRENT_DOCLING` | Gateway concurrency caps | `16` / `10` / `16` |
| `QDRANT_HOST` | Qdrant base URL | `http://localhost:6333` |
| `OLLAMA_HOST` | Ollama base URL | `http://localhost:11434` |
| `DOCLING_HOST` | Docling-serve base URL | `http://localhost:5001` |
| `RCLONE_HOST` | rclone rcd base URL | `http://localhost:5572` |
| `APIFY_KEY` | Apify API token | secret |
| `GEMINI_API_KEY` | Used implicitly by litellm | secret |

Host URLs differ per setup — see the macOS and Linux sections below.

`skills/utils/env.py` auto-loads this file on import (resolved relative to the repo root, so CWD doesn't matter).

## Running a skill

Each skill is a runnable module:

```bash
python -m skills.llm_chat "What is startup due diligence?"
python -m skills.dataset_chat chat <dataset_name> "your question"
```

## Backing services

Four services need to be running before most skills will work: **qdrant**, **ollama**, **docling**, **rclone**.

### macOS

On macOS the services run as a mix of native processes and one container (qdrant), managed by `macos_launch.sh`. The container is launched via `podman compose -f docker-compose.macos.yml` (lighter than the full Linux compose file — only qdrant runs in a container; docling and llama run from a local venv / binary, and rclone mounts via the native CLI).

Prerequisites:
- `podman` (and a running podman machine: `podman machine start`)
- A local Python venv at `./venv` with `docling-serve` installed
- `llama.cpp` checked out at `./llama.cpp` with a model under `./models/`
- `rclone` configured with a `gdrive:` remote

Usage:

```bash
./macos_launch.sh start              # start all four services
./macos_launch.sh start docling      # start one
./macos_launch.sh stop rclone        # stop one
./macos_launch.sh status             # show status of all
```

Services: `qdrant docling llama rclone`. Logs land in `./logs/`, PIDs in `./.pids/`.

With this setup, the four `*_HOST` env vars all point at `localhost` on the standard ports (see table above).

### Linux

On Linux everything runs in containers via the main compose file:

```bash
docker compose -f docker-compose.yml up -d
```

This brings up qdrant, docling-serve (GPU-accelerated), ollama, rclone-mount, plus the openclaw gateway/CLI containers. With this setup the `*_HOST` env vars use the service hostnames (e.g. `http://qdrant:6333`, `http://ollama:11434`) when called from inside the compose network, or `http://host.docker.internal:...` when called from the host.

`docker-compose.yml` also expects a number of host-side variables (`OPENCLAW_*`, `GDRIVE_*`, `OPENCLAW_WORKSPACE_DIR`, etc.) — see the file for the full list.

## Tests

```bash
pytest skills/tests
```
