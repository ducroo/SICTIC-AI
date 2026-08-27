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

The complete set and its local defaults are in `.env-template`. Optional Google
Drive synchronization is configured independently under `rclone-sync/`; it is
not part of the application environment or installer.

## Background services

```bash
./launch.sh start
./launch.sh status
./launch.sh stop
```

The launcher starts Qdrant and, when an `ollama/...` model is configured,
Ollama. It also pulls missing models referenced by `LLM_MODEL`, `VLM_MODEL`, and
`EMBEDDING_MODEL`.

Qdrant startup is serialized with a lock tied to the repository's
`qdrant_data/` directory. The launcher waits for the configured `QDRANT_HOST`
to become ready before reporting success and preserves previous output in
`logs/qdrant.log`. `./launch.sh status qdrant` distinguishes a ready service,
a process that is still starting, a stale PID, and an externally managed
service. It refuses to start a second local Qdrant process when an existing
process or storage lock is detected.

The readiness wait defaults to 600 seconds and polls every two seconds. Large
installations can override these values for a single launch:

```bash
QDRANT_START_TIMEOUT=1800 QDRANT_START_INTERVAL=5 ./launch.sh start qdrant
```

If the timeout expires while Qdrant is still running, the launcher leaves the
process, PID, and storage lock intact for inspection rather than risking a
second start.

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
conda run -n sictic-env python -m skills.bulk_refresh --datasets spacex --skills startup_profile
conda run -n sictic-env python -m skills.dealum_import "Example Startup"
conda run -n sictic-env python -m skills.dataset_maintenance diagnose
```

Consult each skill's `SKILL.md` for its current arguments and examples.

## Google Drive synchronization with rclone

All skills read and write the local filesystem below `LOCAL_STORAGE_PATH`.
Google Drive synchronization is an optional external operation and never runs
inside a skill or through the installer.

Install rclone, create and authenticate a Google Drive remote with
`rclone config`, then run:

```bash
./rclone-sync/configure.sh
./rclone-sync/rclone-sync.sh bootstrap-dry-run
./rclone-sync/rclone-sync.sh bootstrap
```

The guided configuration stores machine-specific paths in the gitignored
`rclone-sync/config.env`. The sync helper keeps its durable bisync listings
under `rclone-sync/state/`, immutable run logs under `rclone-sync/logs/`, and a
continuous operational log under `logs/rclone.log`.

Routine commands are:

```bash
./rclone-sync/rclone-sync.sh dry-run
./rclone-sync/rclone-sync.sh sync
```

The helper imports Markdown as native Google Docs and exports native Google
Docs as Markdown. It also uses access-marker, delete-limit, non-overlap, and
conflict-copy safeguards. Read `rclone-sync/README.md` before bootstrap; rclone
bisync is stateful, and an incorrect resync direction can overwrite the wrong
version.

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

### Tables and spreadsheets

A table that does not fit in one chunk loses its header on the first cut, and
every chunk after that is a block of cells no model can attribute to a column.
Chunking is therefore table-aware. A table larger than one chunk is split on row
boundaries, never mid-row, and every chunk repeats the header. Because each
chunk re-spends part of its budget on that header, tables use a larger chunk
size than prose. This applies wherever tables come from: worksheets, CSV
exports, and tables embedded in PDFs and Word documents.

Tables small enough to survive intact are left alone, inside the prose that
surrounds them, since the sentence before a short table is usually what explains
it.

Where a table carries a GitHub-style separator row, that row identifies the
header and is trusted. Otherwise the header is inferred, because workbooks
routinely stack title and grouping rows above the row that actually names the
columns. A header is recognised by how much more label-like it is than the rows
beneath it, not by an absolute score: a sheet that is simply a column of labelled
values has no header at all, and must not have one of its value rows promoted
into every chunk.

Workbooks are not converted by Docling. They are read directly with `openpyxl`
(or `xlrd` for legacy `.xls`), which keeps hidden rows, hidden columns, hidden
sheets and formula error cells out of the index, and writes one Markdown table
per visible worksheet. Values are rendered the way a reader would write them, so
a share price becomes `15.15` rather than `15.151515151515152`, a
percent-formatted cell becomes `24.69%` rather than `0.24685415429152754`, and a
date becomes `2026-01-19`. Chunks from a workbook are cited by sheet name
instead of a page number.

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
