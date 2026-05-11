# SICTIC-AI

A collection of Python skills (LLM-powered analysis routines for startups, investors, and due-diligence work) backed by local services: Qdrant (vector DB), Ollama (LLM inference), Docling (document parsing), and rclone (Google Drive mount).

## Runtime context

This directory is part of an **openclaw** runtime system — the skills are normally invoked from the openclaw harness via the containerized stack in `docker-compose.yml`. The skills themselves are pure Python and have no hard dependency on openclaw; they could be wired into other harnesses (Claude Code subagents, a CLI runner, an MCP server, etc.) as long as the required env vars and backing services are reachable.

## Prerequisites

Before either OS-specific setup, you need:

- **Homebrew** (macOS): https://brew.sh
- **Miniconda or Anaconda**: `brew install --cask miniconda` (macOS) or https://docs.conda.io
- **Python 3.13** (macOS only, used by the docling venv — see note below): `brew install python@3.13`

## Environment setup (conda)

The canonical Python environment for **running the skills** is defined in `environment.yml` (env name: `sictic-env`, Python 3.12).

```bash
conda env create -f environment.yml
conda activate sictic-env
```

The skills package expects to be importable as `skills.*`. Either run from the repo root or set `PYTHONPATH`:

```bash
export PYTHONPATH="$(pwd)"
```

> **Two Python environments, on purpose.** The skills run in the **conda env (Python 3.12)** described above. The **docling-serve binary** (one of the backing services on macOS) runs from a **separate venv at `./venv` (Python 3.13)**, because docling-serve's dependencies expect 3.13. The two never share an interpreter — keep them separate.

### Configuration: `.env`

Copy the template and fill in values:

```bash
cp .env-template .env
```

Required variables:

| Variable | Purpose | Example |
|---|---|---|
| `GDRIVE_MOUNT` | Local path to the rclone/Google Drive mount | `/data` or `~/gdrive` |
| `WORKSPACE_DIR` | Path to this repo on the host | `/Users/you/.openclaw/workspace-ops/SICTIC-AI` |
| `DEFAULT_LLM`, `DEFAULT_VLM`, `DEFAULT_EMBEDDINGS` | litellm-style model names | `ollama/qwen3:8b` |
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

On macOS **all four services run natively** — no containers, no Linux VM. `macos_launch.sh` manages them as background processes with pidfiles under `./.pids/` and logs under `./logs/`.

#### Prerequisites (macOS-only)

Install the host-side tools via Homebrew:

```bash
brew install rclone ollama
```

**Qdrant** — native macOS binary, downloaded from the official release:

```bash
curl -sL -o /tmp/qdrant.tar.gz \
  https://github.com/qdrant/qdrant/releases/latest/download/qdrant-aarch64-apple-darwin.tar.gz
mkdir -p qdrant && tar -xzf /tmp/qdrant.tar.gz -C qdrant
```

The launcher runs `./qdrant/qdrant` with `QDRANT__STORAGE__STORAGE_PATH=./qdrant_data`, so all state stays under `./qdrant_data/` in the repo.

**Ollama** — runs as a regular process. `macos_launch.sh start ollama` launches `ollama serve` in the background. Do **not** also run `brew services start ollama` — that would start a second instance and fight the launcher for port 11434.

To pre-pull the models referenced in `.env`:

```bash
ollama pull qwen3:8b
ollama pull qwen3-vl:8b
ollama pull qwen3-embedding:8b
ollama pull qwen3:4b
ollama pull qwen3:30b
ollama pull gemma3:27b
```

The set above totals ~55 GB. Trim it to whatever subset you actually need (at minimum: the `DEFAULT_LLM`, `DEFAULT_VLM`, and `DEFAULT_EMBEDDINGS` from `.env`).

**Docling-serve** — installed into a local Python 3.13 venv at `./venv`:

```bash
python3.13 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install docling-serve
```

That installs `docling`, `docling-core`, `docling-ibm-models`, `docling-serve`, plus the FastAPI/uvicorn/torch stack. For optional UI and RAG extras: `./venv/bin/pip install "docling-serve[ui,rag]"`. (Note: this venv is for the docling service binary only. The skills themselves use the conda env from `environment.yml`.)

**rclone** — configure a `gdrive:` remote once:

```bash
rclone config        # follow the interactive flow; name the remote "gdrive"
```

Set `GDRIVE_MOUNT` in `.env` to the absolute path you want the Drive mounted at (e.g. `/Users/you/gdrive`). The launcher creates the directory if missing and starts rclone with `--rc --rc-addr 0.0.0.0:5572` so `RcloneAdapter.refresh_vfs()` works.

#### Usage

```bash
./macos_launch.sh start              # start all four services
./macos_launch.sh start docling      # start one
./macos_launch.sh stop rclone        # stop one
./macos_launch.sh status             # show status of all
```

Services: `qdrant docling ollama rclone`. Logs land in `./logs/`, PIDs in `./.pids/`.

With this setup, the four `*_HOST` env vars all point at `localhost` on the standard ports (see the variable table above).

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
