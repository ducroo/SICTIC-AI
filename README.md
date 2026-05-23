# SICTIC-AI

A collection of Python skills (LLM-powered analysis routines for startups, investors, and due-diligence work) backed by local services: Qdrant (vector DB), Ollama (LLM inference), and Google Drive (either as an rclone FUSE mount or via the native Drive API). Document parsing is done in-process via the [docling](https://github.com/docling-project/docling) library (Apple Vision OCR on macOS).

## Runtime context

This directory is part of an **openclaw** runtime system — the skills are normally invoked from the openclaw harness. The skills themselves are pure Python and have no hard dependency on openclaw; they can be wired into other harnesses (Claude Code subagents, a CLI runner, an MCP server, etc.) as long as the required env vars and backing services are reachable.

The supported platform is **macOS** (Apple Silicon). All services run natively; there is no containerised path.

## Prerequisites

Both install paths need:

- **Homebrew** — https://brew.sh
- **rclone** and **Ollama** — `brew install rclone ollama` (rclone only needed in mount mode; see [Google Drive access](#google-drive-access))
- **Qdrant** — native binary, downloaded separately (see [Backing services](#backing-services))

Then pick **one** of the two Python-env paths below.

### Path A — pip + venv (default)

No extra brew prerequisites — `install_skills.sh` uses whatever `python3.13` (or `python3`) is on `PATH`. macOS ships with Python; if you want a controlled version:

```bash
brew install python@3.13
```

### Path B — conda

```bash
brew install --cask miniforge
conda init zsh        # or `conda init bash`, depending on $SHELL
exec $SHELL           # reload shell so `conda` is on PATH
conda --version       # verify
```

Miniforge is the conda-forge-preconfigured installer, recommended for Apple Silicon. (Miniconda/Anaconda work too, but miniforge avoids Anaconda's licensing concerns and is smaller.)

## Environment setup

### Path A — pip + venv (recommended default)

```bash
./install_skills.sh --target /path/to/openclaw/skill/dir
```

What it does (idempotent — safe to re-run any time):

1. Creates `./venv` (Python 3.13) if missing — or rebuilds it if the venv was copied from another location.
2. Runs `pip install -e .` so the `skills` and `lib` packages plus all runtime deps (from `pyproject.toml`) are installed in the venv and reflect the current location.
3. Mirrors every `skills/<name>/` directory that has a `SKILL.md` into `<target>/<name>/`, substituting `{{REPO_ROOT}}` placeholders in each mirrored `SKILL.md` with this repo's absolute path. The resulting commands point at `./venv/bin/python` directly — no activation required, openclaw can copy-paste them verbatim.

Re-run after moving the repo, editing any `SKILL.md`, or pulling a branch that adds dependencies. Flags: `--target` (required), `--symlink`, `--prune`, `--rebuild-venv`, `--skip-venv`. See `./install_skills.sh --help`.

Resulting Python: `<repo>/venv/bin/python` (1.7 GB env).

### Path B — conda

```bash
./install_skills_conda.sh --target /path/to/openclaw/skill/dir
```

Same idempotent three-step flow as Path A, with the env step swapped:

1. Creates the `sictic-env` conda env from `environment.yml` (Python 3.13, 12 conda-forge deps + 5 pip-section deps), or runs `conda env update --prune` if it already exists.
2. Runs `pip install -e .` inside the conda env.
3. Mirrors skills as above. The substituted SKILL.md commands point at the conda env's absolute python path (e.g. `/opt/homebrew/Caskroom/miniforge/.../envs/sictic-env/bin/python`) — so `conda activate` is not required at invocation time.

Flags mirror Path A: `--target` (required), `--symlink`, `--prune`, `--rebuild-env`, `--skip-env`. See `./install_skills_conda.sh --help`.

Resulting Python: `~/miniforge/envs/sictic-env/bin/python` (or wherever your conda lives). First env-create takes ~5-8 min; subsequent updates < 1 min.

`environment.yml` is kept in sync with `pyproject.toml` — anything you add to one should land in the other.

### Configuration: `.env`

Copy the template and fill in values:

```bash
cp .env-template .env
```

Required variables:

| Variable | Purpose | Example |
|---|---|---|
| `REPOSITORY_DIR` | Local path to the rclone/Google Drive mount | `/data` or `~/gdrive` |
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

`lib/env.py` auto-loads this file on import (resolved relative to the repo root, so CWD doesn't matter).

## Running a skill

After running the installer, each mirrored `SKILL.md` under `<target>/<name>/` contains a ready-to-copy bash command with the absolute Python path already substituted in. The pattern is always:

```bash
<absolute-path-to-python> -m skills.<name> [args]
```

For Path A (venv) installs, that resolves to:

```bash
/abs/path/to/repo/venv/bin/python -m skills.llm_chat "What is startup due diligence?"
/abs/path/to/repo/venv/bin/python -m skills.dataset_chat chat <dataset_name> "your question"
/abs/path/to/repo/venv/bin/python -m skills.startup_profile --startup "<startup_name>" --files /path/to/deck.pdf
```

For Path B (conda) installs, the prefix is the conda env's python instead — e.g. `/opt/homebrew/Caskroom/miniforge/.../envs/sictic-env/bin/python -m skills.…`.

Either way, no activation is needed. If you'd rather work from an activated shell:

```bash
# Path A
source venv/bin/activate
python -m skills.llm_chat "..."

# Path B
conda activate sictic-env
python -m skills.llm_chat "..."
```

## Backing services

Three services need to be running before most skills will work: **qdrant**, **ollama**, **rclone** (only in mount mode). `macos_launch.sh` manages them as background processes with pidfiles under `./.pids/` and logs under `./logs/`.

### Install the host-side tools

`rclone` and `ollama` come from the Prerequisites step above (`brew install rclone ollama`). The remaining pieces:

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

**docling** — installed into the Python env automatically by either installer (`docling[ocrmac]` + `ocrmac` from `pyproject.toml` / `environment.yml`). The `ocrmac` package routes OCR through Apple's Vision framework (Neural Engine accelerated on Apple Silicon). First convert call downloads the docling layout + table models (~1 GB) into `~/.cache/docling/`; subsequent runs reuse them.

**rclone** — configure a `gdrive:` remote once (skip in Drive API mode):

```bash
rclone config        # follow the interactive flow; name the remote "gdrive"
```

Set `REPOSITORY_DIR` in `.env` to the absolute path you want the Drive mounted at (e.g. `/Users/you/gdrive`). The launcher creates the directory if missing and starts rclone with `--rc --rc-addr 0.0.0.0:5572`.

### Launcher

```bash
./macos_launch.sh start              # start all three services
./macos_launch.sh start qdrant       # start one
./macos_launch.sh stop rclone        # stop one
./macos_launch.sh status             # show status of all
```

## Google Drive access

All skills read/write Drive through `lib.storage.get_storage()`, which returns one of two backends depending on env vars:

| Mode | Backend | Required setup |
|---|---|---|
| **Mount** *(default, `GDRIVE_USE_API` unset)* | `LocalStorage($REPOSITORY_DIR)` reading the FUSE mount | rclone configured + running (see rclone setup above) |
| **API** *(`GDRIVE_USE_API=1`)* | `GoogleDriveStorage` — native Drive API via `google-api-python-client` | OAuth credentials (below); no rclone needed |

In both modes, cache-only paths (`datasets_parsed/…`) are automatically routed to the local `CACHE_DIR` (`~/.cache/sictic` by default), so re-derivable artifacts never round-trip through Drive.

### API-mode setup

Four steps total. The first two happen in [Google Cloud Console](https://console.cloud.google.com) (one-time per Google account); the last two are local.

**1. Create a project and enable the Drive API.**

- Create a new project (or pick an existing one) — e.g. `ai-sictic`.
- **APIs & Services → Library** → search "Google Drive API" → **Enable**.

**2. Create OAuth credentials.**

- **APIs & Services → OAuth consent screen** → User type **External**. Add yourself as a test user. Skip the scope step — `https://www.googleapis.com/auth/drive` is requested at runtime, not declared up front.
- **APIs & Services → Credentials → Create credentials → OAuth client ID**.
  - **Application type: `Desktop app`** ← important; *not* "Web application". Desktop-app clients support the loopback redirect that the Python flow uses, and download as a JSON with `"installed"` as the top-level key. Web-app clients download with `"web"` and won't work with `InstalledAppFlow`.
  - Name it anything (e.g. `sictic-ops`).
- **Download the JSON.**

**3. Save credentials + enable API mode locally.**

```bash
mv ~/Downloads/client_secret_*.json ~/.openclaw/gdrive-ops-credentials.json
echo "GDRIVE_USE_API=1" >> .env
```

(If you keep the credentials at a different path, set `GDRIVE_CREDENTIALS=/your/path` in `.env`.)

**4. Verify — the first run completes OAuth and caches a refresh token.**

```bash
# Path A
./venv/bin/python -c "
import lib.env
from lib.storage import get_storage
s = get_storage()
print('backend:', type(s).__name__)
print('datasets/:', s.list('datasets')[:5])
"

# Path B
conda run -n sictic-env --no-capture-output python -c "
import lib.env
from lib.storage import get_storage
s = get_storage()
print('backend:', type(s).__name__)
print('datasets/:', s.list('datasets')[:5])
"
```

On the first run, your browser opens for the OAuth grant. After you approve, a refresh token gets cached at `~/.openclaw/gdrive-ops-token.json` (override with `GDRIVE_TOKEN`) and subsequent runs use it silently.

Expected output: `backend: RoutedStorage`, followed by up to 5 dataset names from your Drive root (`[]` if `datasets/` is empty on Drive).

To revoke or rotate access, delete `~/.openclaw/gdrive-ops-token.json` and re-run — the OAuth flow fires again.

For a deeper smoke test that exercises every storage operation (write/read/list/mkdir/rmtree/mtime) against the live Drive API, run `tests/utils/test_storage_api_smoke.py`:

```bash
./venv/bin/python tests/utils/test_storage_api_smoke.py
```

## Tests

```bash
# Path A
./venv/bin/python -m pytest tests/

# Path B
conda run -n sictic-env --no-capture-output pytest tests/
```

`tests/utils/test_storage_api_smoke.py` is a useful end-to-end probe — it exercises every `lib.storage` method against the currently configured backend (LocalStorage in mount mode, GoogleDriveStorage when `GDRIVE_USE_API=1`).
