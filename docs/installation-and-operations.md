# Installation and operations

This guide contains the detailed setup and operational material intentionally
kept out of the main README.

## Runtime requirements

SICTIC-AI supports macOS, Linux, and WSL2. It requires Conda and is designed to
be used with a coding agent such as OpenClaw, Claude Code, Codex, or Gemini.

### Install Miniforge

On macOS:

```bash
brew install --cask miniforge
conda init zsh                 # or bash
exec $SHELL
```

On Ubuntu or WSL2:

```bash
sudo apt update && sudo apt install -y curl wget
wget "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"
bash Miniforge3-*.sh
exec $SHELL
```

Install Ollama if you plan to use the local `ollama/...` models provided as the
defaults in `.env-template`:

```bash
# macOS
brew install ollama

# Linux or WSL2
curl -fsSL https://ollama.com/install.sh | sh
```

Qdrant does not require a separate installation. `./launch.sh start` downloads
the matching binary into `qdrant/` and uses `qdrant_data/` for its local data.

## Run the installer

```bash
./install.sh
```

The installer creates or updates the `sictic-env` Conda environment, registers
the repository on its Python import path, optionally copies skills into an
agent's skills directory, and configures `.env`.

Use repository-only mode if you do not want copied skills. At the installed
skills prompt, enter `none` or accept `[none]`. You can still invoke every skill
through the repository's Python commands.

Useful options:

```bash
./install.sh --target /absolute/path/to/agent/skills
./install.sh --rebuild-env
./install.sh --skip-env
./install.sh --non-interactive
```

Re-run the installer after changing `SKILL.md` files if you use copied skills.

## Environment configuration

The main path variables are documented in the README. Other important groups
are:

- `LLM_*`: primary text-generation model, endpoint, and API key.
- `VLM_*`: image and chart interpretation model, endpoint, and API key.
- `EMBEDDING_*`: semantic-search embedding model, endpoint, and API key.
- `QDRANT_HOST`: Qdrant service URL.
- `OLLAMA_HOST`: local Ollama service URL.
- `RANKED_LLMS`: preferred model order when reusing existing insights.
- `RERANK_*`: optional cross-encoder that rescores retrieved chunks, its
  endpoint, and API key. Blank `RERANK_MODEL` disables reranking.
- `RETRIEVAL_*`: how wide retrieval runs and how much of an answer one document
  may occupy. See [Retrieval](#retrieval).

The complete set and its local defaults are in `.env-template`.

Cloud storage is optional. With blank `CLOUD_PROVIDER`, skills use only local
storage and the installer skips Google Drive configuration. Set
`CLOUD_PROVIDER=google` to enable the standalone synchronization utility.

## Background services

```bash
./launch.sh start
./launch.sh status
./launch.sh stop
```

The launcher starts Qdrant and, when an `ollama/...` model is configured,
Ollama. It also pulls missing models referenced by `LLM_MODEL`, `VLM_MODEL`, and
`EMBEDDING_MODEL`.

## Command interfaces

Use the harness for stable user-facing slash commands:

```bash
conda run -n sictic-env python -m skills.harness /startup_profile SpaceX
conda run -n sictic-env python -m skills.harness /dd_checks SpaceX
conda run -n sictic-env python -m skills.harness /dataset_chat SpaceX "What are the main risks?"
```

Start the interactive harness with `--no-capture-output` so Conda keeps stdin
open:

```bash
conda run -n sictic-env --no-capture-output python -m skills.harness
```

Administrative skills with their own command-line options are invoked directly:

```bash
conda run -n sictic-env python -m skills.bulk_refresh --dataset spacex --skill startup_profile
conda run -n sictic-env python -m skills.dealum_import "Example Startup"
conda run -n sictic-env python -m skills.dataset_maintenance diagnose
```

Consult each skill's `SKILL.md` for its current arguments and examples.

## Google Drive synchronization

All skills read and write the local filesystem below `LOCAL_STORAGE_PATH`.
Google Drive access is isolated in the `gdrive_sync` utility under
`gdrive-sync/`; normal application storage never accesses Drive directly.

Required `.env` values:

- `CLOUD_PROVIDER=google`
- `LOCAL_STORAGE_PATH`: the local application storage root.
- `CLOUD_STORAGE_PATH`: a Drive folder ID, `root`, or folder path/name.
- `GDRIVE_CREDENTIALS`: OAuth Desktop-App credentials JSON.
- `GDRIVE_TOKEN`: cached OAuth token JSON.

Ask your coding agent to guide you through creating a Google OAuth Desktop-App
client and authenticating it.

Common commands:

```bash
python -m gdrive_sync pull
python -m gdrive_sync sync --conflict-policy cloud-wins
python -m gdrive_sync sync --conflict-policy local-wins
```

- `pull` makes local storage match Drive and establishes the initial baseline.
- `cloud-wins` downloads cloud additions and updates without deleting files.
- `local-wins` synchronizes both ways and keeps the local version on conflicts.
- `--dry-run` previews changes; `--json` produces machine-readable output.

The initial pull can take hours for a large Drive. Later synchronizations use a
stored baseline and the Google Drive Changes API. Google Drive shortcuts are not
supported inside the synchronized root.

The synchronization baseline lives below
`<REPO_PATH>/gdrive_sync_state/<pairing-id>/`. It is durable state and must
not be deleted during cache cleanup.

## Retrieval

Search over a data room runs in three stages.

**1. Hybrid retrieval.** Every question is matched twice against the same Qdrant
collection: once as a dense embedding, and once as BM25 keyword terms. Qdrant
fuses the two rankings with reciprocal rank fusion. The dense side handles
paraphrases, and the BM25 side handles the exact strings that matter in a data
room and that a small local embedding model tends to blur, such as
`Inventionsabtretungserklärung`, `Art. 332 OR`, or a specific patent number.
BM25 needs no extra model or service: Qdrant computes the inverse document
frequency itself, so only term frequencies are stored alongside each chunk.

**2. Optional reranking.** When `RERANK_MODEL` is set, a cross-encoder rescores
the retrieved candidates by reading the question and the chunk together. This is
off by default. A local reranker keeps confidential documents on the machine,
for example a self-hosted [Infinity](https://github.com/michaelfeil/infinity)
server:

```bash
RERANK_MODEL="infinity/BAAI/bge-reranker-v2-m3"
RERANK_BASE_URL=http://localhost:7997
```

If the reranker is unreachable or fails, retrieval keeps the fusion order and
logs a warning, so search never breaks because of it.

**3. Diversification.** Retrieval runs wider than the requested chunk count
(`RETRIEVAL_CANDIDATE_MULTIPLIER`) and then caps how much of the answer a single
document may occupy (`RETRIEVAL_MAX_DOCUMENT_SHARE`). This stops one long
document, such as a 200-page shareholder agreement, from filling the whole
context and hiding the cap table. Chunks above the cap are demoted rather than
dropped, so the requested number of chunks is still returned.

### Upgrading an existing index

Qdrant cannot add sparse vectors to a collection that was created without them,
so datasets indexed before hybrid search keep working as dense-only search until
their collection is rebuilt:

```bash
python -m skills.dataset_maintenance rebuild-index --dataset avientus
```

This drops the Qdrant collection and re-embeds the dataset. Parsed Markdown is
kept, so documents are never sent through Docling again. Rebuilding is the
expensive step for a large data room; run it once per dataset when convenient.

## Dataset maintenance

```bash
python -m skills.dataset_maintenance diagnose
python -m skills.dataset_maintenance prune
python -m skills.dataset_maintenance prune --apply
python -m skills.dataset_maintenance migrate-startup-dossiers
python -m skills.dataset_maintenance rebuild-index --dataset avientus
```

Pruning is a dry run unless `--apply` is supplied. `rebuild-index` re-embeds a
dataset without re-parsing it; see [Retrieval](#retrieval).

## Tests

```bash
conda run -n sictic-env python -m pytest -q
```

The default suite uses isolated local storage and mocked external services.
Opt-in live tests require their external services and datasets:

```bash
SICTIC_RUN_LIVE_SMOKE=1 conda run -n sictic-env python -m pytest -q -m live
```
