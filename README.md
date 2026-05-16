# SICTIC-AI

A collection of Python skills (LLM-powered analysis routines for startups, investors, and due-diligence work) backed by local services: Qdrant (vector DB), Ollama (LLM inference), and Google Drive (either as an rclone FUSE mount or via the native Drive API). Document parsing is done in-process via the [docling](https://github.com/docling-project/docling) library (Apple Vision OCR on macOS).

## Runtime context

This directory is part of an **openclaw** runtime system — the skills are normally invoked from the openclaw harness. The skills themselves are pure Python and have no hard dependency on openclaw; they can be wired into other harnesses (Claude Code subagents, a CLI runner, an MCP server, etc.) as long as the required env vars and backing services are reachable.

The supported platform is **macOS** (Apple Silicon). All services run natively; there is no containerised path.

## Prerequisites

- **Homebrew**: https://brew.sh
- **Miniconda or Anaconda**: `brew install --cask miniconda`

## Environment setup (conda)

The canonical Python environment for **running the skills** is defined in `environment.yml` (env name: `sictic-env`, Python 3.12).

```bash
conda env create -f environment.yml
conda activate sictic-env
```

`environment.yml` includes `--editable .`, so `pip` installs the `skills` package in editable mode as part of env creation. After that, `import skills.foo.bar` works from any directory, without needing `PYTHONPATH`. If you ever bootstrap a venv by hand instead of conda, run `pip install -e .` from the repo root once.

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
| `APIFY_KEY` | Apify API token | secret |
| `GEMINI_API_KEY` | Used implicitly by litellm | secret |

Optional — Drive API mode (see [Google Drive access](#google-drive-access)):

| Variable | Purpose | Default |
|---|---|---|
| `GDRIVE_USE_API` | `1` to talk to Drive's REST API directly (no rclone); anything else uses the mount | unset |
| `GDRIVE_CREDENTIALS` | Path to the Desktop-app OAuth `credentials.json` | `~/.openclaw/gdrive-ops-credentials.json` |
| `GDRIVE_TOKEN` | Path where the refresh token is cached | `~/.openclaw/gdrive-ops-token.json` |
| `GDRIVE_ROOT_FOLDER_ID` | Drive folder ID to treat as the storage root | `root` (your My Drive root) |
| `CACHE_DIR` | Local cache dir for re-derivable artifacts (`datasets_parsed/…`) | `~/.cache/sictic` |

`skills/utils/env.py` auto-loads this file on import (resolved relative to the repo root, so CWD doesn't matter).

## Running a skill

Use the repo's `./run` wrapper — it picks the right Python interpreter
automatically (preferring `./venv/bin/python`, then `python` on PATH), and you
can override it with the `SICTIC_PYTHON` env var:

```bash
./run llm_chat "What is startup due diligence?"
./run dataset_chat chat <dataset_name> "your question"
./run startup_profile --startup "<startup_name>" --files /path/to/deck.pdf
```

Under the hood it's just `<interpreter> -m skills.<name> [args]`, so you can
also invoke skills directly if you've activated the right Python yourself
(e.g. `conda activate sictic-env`):

```bash
python -m skills.llm_chat "What is startup due diligence?"
```

## Backing services

Three services need to be running before most skills will work: **qdrant**, **ollama**, **rclone** (mount-mode only — skip if using Drive API mode).

Document parsing (OCR) is done in-process by the `docling` Python library — no separate service to start.

`macos_launch.sh` manages them as background processes with pidfiles under `./.pids/` and logs under `./logs/`.

### Install the host-side tools

Via Homebrew:

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

**docling** — installed into the conda env via `environment.yml` (`docling[ocrmac]` + `ocrmac`). The `ocrmac` package routes OCR through Apple's Vision framework (Neural Engine accelerated on Apple Silicon). First convert call downloads the docling layout + table models (~1 GB) into `~/.cache/docling/`; subsequent runs reuse them.

**rclone** (mount mode only — skip if you'll use [Drive API mode](#google-drive-access)) — configure a `gdrive:` remote once:

```bash
rclone config        # follow the interactive flow; name the remote "gdrive"
```

Set `GDRIVE_MOUNT` in `.env` to the absolute path you want the Drive mounted at (e.g. `/Users/you/gdrive`). The launcher creates the directory if missing and starts rclone with `--rc --rc-addr 0.0.0.0:5572`.

### Launcher

```bash
./macos_launch.sh start              # start all three services
./macos_launch.sh start qdrant       # start one
./macos_launch.sh stop rclone        # stop one
./macos_launch.sh status             # show status of all
```

Services: `qdrant ollama rclone`. Logs land in `./logs/`, PIDs in `./.pids/`. The `*_HOST` env vars all point at `localhost` on the standard ports (see the variable table above).

## Google Drive access

All skills read/write Drive through `skills.utils.storage.get_storage()`, which returns one of two backends depending on env vars:

| Mode | Backend | Required setup |
|---|---|---|
| **Mount** *(default)* | `LocalStorage($GDRIVE_MOUNT)` reading the FUSE mount | rclone configured + running (see rclone setup above) |
| **API** | `GoogleDriveStorage` — native Drive API via `google-api-python-client` | OAuth credentials (below); no rclone needed |

Set `GDRIVE_USE_API=1` in `.env` to switch to API mode. With it unset, you get mount mode.

In both modes, cache-only paths (`datasets_parsed/…`) are automatically routed to the local `CACHE_DIR` (`~/.cache/sictic` by default), so re-derivable artifacts never round-trip through Drive.

### API-mode setup

One-time setup against a Google Cloud project:

1. **Create / pick a Google Cloud project.** Go to [console.cloud.google.com](https://console.cloud.google.com), create a project (or use an existing one) — e.g. `ai-sictic`.
2. **Enable the Google Drive API.** APIs & Services → Library → search "Google Drive API" → Enable.
3. **Configure the OAuth consent screen** (only required once per project). User type: **External**. Add yourself as a test user. Scope `https://www.googleapis.com/auth/drive` is requested at runtime — you don't need to add it here.
4. **Create OAuth credentials.** APIs & Services → Credentials → **Create credentials → OAuth client ID**.
   - **Application type: `Desktop app`.** This is important — *not* "Web application". Desktop-app clients support the loopback redirect that the Python flow uses, and download as a JSON with `"installed"` as the top-level key. Web-app clients download with `"web"` and won't work with `InstalledAppFlow`.
   - Name it anything (e.g. `sictic-ops`).
5. **Download the JSON** and place it at:
   ```
   ~/.openclaw/gdrive-ops-credentials.json
   ```
   (or any path you prefer, then set `GDRIVE_CREDENTIALS=/some/path` in `.env`).
6. **First run.** On the first call to `get_storage()` in API mode, the OAuth flow opens your browser, you grant the requested Drive access, and a refresh token is cached at `~/.openclaw/gdrive-ops-token.json` (override with `GDRIVE_TOKEN`). Subsequent runs reuse the token silently.

Quick verification:

```bash
GDRIVE_USE_API=1 PYTHONPATH=. python -c "
from skills.utils.storage import get_storage
s = get_storage()
print(s.list('datasets'))
"
```

If you ever need to revoke or rotate access, delete `~/.openclaw/gdrive-ops-token.json` and re-run — the OAuth flow will fire again.

## Tests

```bash
pytest skills/tests
```
