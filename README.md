# SICTIC-AI

A collection of Python skills (LLM-powered analysis routines for startups, investors, and due-diligence work) backed by local services: Qdrant (vector DB), Ollama (LLM inference), and Google Drive (native Drive API). Document parsing is done in-process via the [docling](https://github.com/docling-project/docling) library (Apple Vision OCR on macOS).

## Runtime context

This directory is part of an **openclaw** runtime system — the skills are normally invoked from the openclaw harness. The skills themselves are pure Python and have no hard dependency on openclaw; they can be wired into other harnesses (Claude Code subagents, a CLI runner, an MCP server, etc.) as long as the required env vars and backing services are reachable.

## Prerequisites

- **Homebrew** — https://brew.sh
- **Conda (Miniforge)** — recommended for Apple Silicon Python management

```bash
brew install --cask miniforge
conda init zsh        # or `conda init bash`, depending on $SHELL
exec $SHELL           # reload shell so `conda` is on PATH
conda --version       # verify
```

*(Optional but Recommended)*
- **Ollama** — `brew install ollama` (Local models are highly recommended; cloud models can become expensive during batch document processing).

## Environment setup

```bash
./install_skills_conda.sh --target /path/to/openclaw/skill/dir
```

What it does (idempotent — safe to re-run any time):

1. Creates the `sictic-env` conda env from `environment.yml` (Python 3.13), or runs `conda env update --prune` if it already exists.
2. Runs `pip install -e .` inside the conda env.
3. Symlinks every `skills/<name>/` directory that has a `SKILL.md` into `<target>/<name>/`. **Any edits made to skills in the workspace will instantly reflect in the Git repository.** The installer explicitly skips any real directories in the target to protect un-ingested user skills.

### Configuration: `.env`

Copy the template and fill in values:

```bash
cp .env-template .env
```

| Variable | Purpose | Example |
|---|---|---|
| `WORKSPACE_DIR` | Path to this repo on the host | `/Users/you/.openclaw/workspace-ops/SICTIC-AI` |
| `STORAGE_PROVIDER` | `local` or `google` | `local` |
| `STORAGE_PATH` | If `local`: absolute path. If `google`: Folder ID or `root` | `/data` or `1A2B3C...` |
| `DEFAULT_LLM`, `DEFAULT_EMBEDDINGS` | litellm-style model names | `ollama/qwen3:8b` |
| `OLLAMA_MAX_CONTEXT`, `OLLAMA_CONTEXT_LENGTH` | Context window sizing | `32768` / `16384` |
| `RANKED_LLMS` | Preferred LLM fallback order (CSV) | see `.env-template` |
| `MAX_CONCURRENT_EMBEDS`, `MAX_CONCURRENT_LLMS`, `MAX_CONCURRENT_DOCLING` | Gateway concurrency caps | `16` / `10` / `16` |
| `QDRANT_HOST` | Qdrant base URL | `http://localhost:6333` |
| `OLLAMA_HOST` | Ollama base URL | `http://localhost:11434` |

Optional — Google Drive API configuration:

| Variable | Purpose | Default |
|---|---|---|
| `GDRIVE_CREDENTIALS` | Path to the Desktop-app OAuth `credentials.json` | `~/.openclaw/gdrive-ops-credentials.json` |
| `GDRIVE_TOKEN` | Path where the refresh token is cached | `~/.openclaw/gdrive-ops-token.json` |
| `CACHE_DIR` | Local cache dir for parsed PDFs (`datasets_parsed/…`) | `~/.cache/sictic` |

`lib/env.py` auto-loads this file on import.

## Running a skill

Skills are executed universally via `conda run`. No virtual environment activation is needed. The invocation command is always identical across macOS and Linux:

```bash
conda run -n sictic-env python -m skills.llm_chat "What is startup due diligence?"
conda run -n sictic-env python -m skills.dataset_chat chat <dataset_name> "your question"
```

## Backing services

One service **must** be running before skills will work: **qdrant**. 
**ollama** is strictly optional if you rely on cloud models, but running it locally is recommended for cost control.

`launch.sh` manages them as background processes with pidfiles under `./.pids/` and logs under `./logs/`.

**Qdrant** — the launcher script will automatically download the correct native binary for your OS (macOS or Linux) and architecture into the `./qdrant/` directory.

**Ollama (Optional)** — runs as a regular process or system service. The launcher intelligently checks if Ollama is already responding on port 11434 before attempting to start a local daemon instance.

To pre-pull the models referenced in `.env`:

```bash
ollama pull qwen3:8b
ollama pull qwen3-embedding:8b
```

### Launcher

```bash
./launch.sh start              # start all services
./launch.sh start qdrant       # start one
./launch.sh stop ollama        # stop one
./launch.sh status             # show status of all
```

## Google Drive access (Optional)

Using Google Drive is strictly optional. By default (`STORAGE_PROVIDER="local"`), all data is written to and read from the local file system path provided in `STORAGE_PATH`. Local files work perfectly fine.

However, in production we use Google Drive to seamlessly share datasets and insights with Deal Leads. If `STORAGE_PROVIDER="google"`, skills read/write directly to Drive through the native Google Drive API via `google-api-python-client`.

In Google Drive mode, `STORAGE_PATH` **must** be a unique Google Drive Folder ID (e.g., `1A2B3C...`), or explicitly set to `root`. It cannot be a folder path string like `/repository/`.

### API-mode setup

Four steps total. The first two happen in [Google Cloud Console](https://console.cloud.google.com) (one-time per Google account); the last two are local.

**1. Create a project and enable the Drive API.**

- Create a new project (or pick an existing one) — e.g. `ai-sictic`.
- **APIs & Services → Library** → search "Google Drive API" → **Enable**.

**2. Create OAuth credentials.**

- **APIs & Services → OAuth consent screen** → User type **External**. Add yourself as a test user. Skip the scope step — `https://www.googleapis.com/auth/drive` is requested at runtime, not declared up front.
- **APIs & Services → Credentials → Create credentials → OAuth client ID**.
  - **Application type: `Desktop app`** ← important; *not* "Web application". Desktop-app clients support the loopback redirect that the Python flow uses, and download as a JSON with `"installed"` as the top-level key.
  - Name it anything (e.g. `sictic-ops`).
- **Download the JSON.**

**3. Save credentials + enable API mode locally.**

```bash
mv ~/Downloads/client_secret_*.json ~/.openclaw/gdrive-ops-credentials.json
```
Edit your `.env` to set `STORAGE_PROVIDER="google"` and `STORAGE_PATH="<your_folder_id>"`.

**4. Verify — the first run completes OAuth and caches a refresh token.**

```bash
conda run -n sictic-env --no-capture-output python -c "
import lib.env
from lib.storage import get_storage
s = get_storage()
print('backend:', type(s).__name__)
print('datasets/:', s.list('datasets')[:5])
"
```

On the first run, your browser opens for the OAuth grant. After you approve, a refresh token gets cached at `~/.openclaw/gdrive-ops-token.json` (override with `GDRIVE_TOKEN`) and subsequent runs use it silently.

Expected output: `backend: RoutedStorage`, followed by up to 5 dataset names.

## Contributing via Git

Because the OpenClaw workspace is symlinked directly to the repository, you can safely create new skills or edit existing ones directly inside the UI.

To synchronize your changes with GitHub without using the terminal, simply trigger the `sictic_git_sync` skill. The AI will act as an architectural gatekeeper—reviewing your code, refactoring any OS-specific or hardcoded paths, ingesting new skills, and automatically committing and pushing the updates for you.

## Tests

```bash
conda run -n sictic-env --no-capture-output pytest tests/
```

