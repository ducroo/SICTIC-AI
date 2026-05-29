# SICTIC-AI

![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)
![License MIT](https://img.shields.io/badge/license-MIT-green.svg)
![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)

Welcome to the SICTIC-AI toolkit! This is an open-source collection of AI-powered analysis routines (AKA skills) designed to supercharge the startup ecosystem. It is completely free to use and easy to contribute to! 

This toolkit serves four audiences:
* **Startups:** Prepare for your first funding round by running our AI over your data room for a dry run.
* **Business Angels:** Automate common assessments in your Due Diligence process.
* **BA Clubs (like SICTIC):** Automate member engagement, startup selection, DD, and monitoring past transactions.
* **AI Wizards:** Co-develop and refine the future of early stage funding rounds with us!

## Available Skills

| Category | Skill | Status | Description |
|---|---|---|---|
| **Community** | `expert_search` | ✅ | Identifies club members with relevant domain expertise to assist with due diligence or operational support |
| | `potential_investors` | ✅ | Identifies potential investors for a startup |
| | `advocates` | ✅ | Identifies inspiring members to represent the organization at external events |
| | `investment_appetite` | ✅ | Articulates and maps the specific investment sweet spot and thesis for each member |
| | `suggested_startups` | ✅ |  Proposes 5–7 attractive startups in active fundraising to each members |
| **Startup Selection & Jury** | `submission_ready` | | Basic check to verify if a startup's application and submitted materials are complete |
| | `pitch_ready` | | Evaluates the clarity and completeness of the startup's materials and value proposition for investor pitch sessions |
| **Due Diligence** | `startup_profile` | ✅ | Generates a succinct overview of the startup. Serves as input for many other skills |
| | `team_profile` | ✅ | Provides a balanced assessment of individual founders and the complete team dynamics |
| | `person_profile` | ✅ | Generates a comprehensive profile for any person in a dataset (either a founder or a club member) |
| | `startup_traction` | ✅ | Summarizes and provides a quantified overview of the startup's market traction |
| | `dd_checks` | ✅ | Executes a comprehensive suite of 100+ due diligence checks on a startup |
| | `market_review` | | Analyzes the target market, customer needs, competitive landscape, and potential substitutes |
| | `t&c_review` | | Reviews and assesses the terms and conditions of the proposed funding round |
| **Ongoing Monitoring** | `alerts&news` | | Monitors and interprets relevant news and updates concerning portfolio startups |
| | `startup_support` | | Coordinates and schedules operational support provided to the startup by investors |
| | `portfolio_mgmt` | | Generates risk-return overviews and performance metrics for a portfolio of startups |


## Contributing

The setup is deliberately simple so everyone can join and co-develop:
* This is about investing expertise and insight, not IT know-how.
* You can safely create new skills or edit existing ones directly inside your UI. 
* Then your AI agent will do the syncing to github for you; it has a  `sictic_git_sync` skill. This skill also acts as an architectural gatekeeper—reviewing your code, enforcing the simplicity standards

## Runtime Context

The toolkit requires a Unix environment (**macOS, Linux, or WSL2**) and an AI Agent 
(like **OpenClaw, Claude Code, or Gemini Spark**) to converse with the skills. 
We primarily develop using macOS and OpenClaw, but the architecture is OS-agnostic.

## Quickstart Setup

Five steps to get the toolkit working on your machine:

### Step 1: Install Prerequisites

You need a package manager and Conda to handle the Python environment.

**macOS (using Homebrew):**
```bash
brew install --cask miniforge
conda init zsh        # or `conda init bash`, depending on your terminal
exec $SHELL           # reload your terminal
```

**Linux / WSL2 (Ubuntu):**
```bash
sudo apt update && sudo apt install -y curl wget
wget "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"
bash Miniforge3-*.sh  # Follow the prompts, say 'yes' to init
exec $SHELL           # reload your terminal
```

Install **Ollama** when using local `ollama/...` models. Local models are the
default in `.env-template` and are useful for heavy document parsing.
* **macOS:** `brew install ollama`
* **Linux/WSL2:** `curl -fsSL https://ollama.com/install.sh | sh`

Qdrant is required for semantic search. You do not need to install it manually:
`./launch.sh start` downloads the matching Qdrant binary for macOS or Linux into
`./qdrant/` and starts it with local storage in `./qdrant_data/`.

### Step 2: Install the Environment

Run the provided installer. This creates a self-contained Python environment (`sictic-env`) 
and inserts the toolkit in your workspace using **symlinks**.

```bash
# macOS example
./install_skills_conda.sh --target /Users/you/.openclaw/workspace-ops/skills

# Linux / WSL2 example
./install_skills_conda.sh --target "$HOME/.openclaw/workspace-ops/skills"
```

The installer creates the same `sictic-env` on macOS and Linux. Docling uses
Apple Vision OCR through `ocrmac` on macOS and RapidOCR on Linux; both paths use
the same `skills.dataset_chat` ingestion code.

### Step 3: Configuration

The installer creates `.env` from `.env-template` if needed and prompts for the
runtime values. Press Enter to accept the value shown in brackets. You need to
configure these variables:

| \# | Variable | Purpose | Example |
|---|---|---|---|
|1| `WORKSPACE_DIR` | Absolute path to the AI workspace skills directory | `/Users/you/.openclaw/workspace-ops/skills` |
|2| `REPO_DIR` | Absolute path to the root of this SICTIC-AI git repository | `/Users/you/SICTIC-AI` |
|3| `STORAGE_PROVIDER` | Where should data be saved? (`local` or `google`) | `local` |
|4| `STORAGE_PATH` | If `local`: absolute path. If `google`/`hybrid`: Drive folder ID, `root`, or folder path/name | `/Users/you/sictic_data`, `SICTIC-AI`, or `root` |
|5| `LLM_MODEL` | The primary text-generation model used for analysis | `google/gemini-flash-latest` or `ollama/qwen3:8b` |
|6| `LLM_BASE_URL` | Base URL for the text-generation endpoint; blank uses the provider default | `http://localhost:11434` |
|7| `LLM_API_KEY` | API key for the text-generation endpoint when needed | blank for local Ollama |
|8| `EMBEDDING_MODEL` | The model used for semantic search embeddings | `ollama/qwen3-embedding:8b` or `openai/text-embedding-3-small` |
|9| `EMBEDDING_BASE_URL` | Base URL for the embedding endpoint; blank uses the provider default | `http://localhost:11434` |
|10| `EMBEDDING_API_KEY` | API key for the embedding endpoint when needed | blank for local Ollama |
|11| `DEFAULT_VLM` | The model used for extracting text from images/charts | `ollama/qwen3-vl:8b` or `openai/gpt-4o-mini` |
|12| `RANKED_LLMS` | If insights md files were created with several models, the preferred ranking for re-use. (CSV list) | see `.env-template` |

*(Note: The other variables in `.env-template` are explained inline. You don't need to change them).*
`DEFAULT_LLM` and `DEFAULT_EMBEDDINGS` are still accepted as compatibility aliases, but new installs should configure `LLM_*` and `EMBEDDING_*`.

### Step 4: Start Background Services

SICTIC-AI relies on Qdrant for semantic search and on Ollama when any configured
model starts with `ollama/`. The launcher downloads Qdrant when needed, starts
Qdrant and Ollama, and pulls the Ollama models referenced by `LLM_MODEL`,
`EMBEDDING_MODEL`, and `DEFAULT_VLM` if they are not already available.

```bash
./launch.sh start
./launch.sh status  # check running services
./launch.sh stop    # shut down local background services
```

### Step 5: Run a Skill

You are ready to go! Execution of skills is straightforward. Either you ask your AI Agent to do so, or us the CLI: 

```bash
conda run -n sictic-env python -m skills.llm_chat "What is startup due diligence?"
conda run -n sictic-env python -m skills.startup_profile --startup "SpaceX"
```

For manual end-to-end testing, use the lightweight slash-command harness:

```bash
conda run -n sictic-env python -m skills.harness
```

Inside the harness, run `/help` to list commands such as `/dataset_chat <dataset> <question>`, `/startup_profile <startup>`, and `/dd_checks <startup>`.

<details>
<summary>▶ Click to see a sample Startup Profile output for SpaceX</summary>

```markdown
# Startup Profile: SpaceX

1. **Oneliner:** Design, manufacture, and launch of advanced rockets and spacecraft.
2. **Core industry:** Aerospace Manufacturing and Space Transportation Services.
3. **Technology:** Highly verticalized manufacturing of reusable launch vehicles (Falcon 9, Starship); significant reliance on complex materials science, extreme-environment engineering, and proprietary autonomous landing software. Technical single point of failure lies in the unproven orbital refueling and heat shield viability of the Starship platform.
4. **Business model:** B2B/B2G payload launch services (commercial satellites, NASA/DoD contracts) and B2C direct-to-consumer satellite internet (Starlink). Structural risks include astronomical capital expenditure requirements, reliance on favorable government regulatory environments, and the inherent binary risk of catastrophic mission failures destroying hardware and client payloads.
5. **Current challenges:** Scaling Starship production to achieve promised launch cadence and cost-reduction; navigating intense FAA environmental and launch licensing scrutiny; proving the economic viability of the Starlink constellation against hardware degradation timelines. Expert due diligence required on Starship payload capacities and orbital refueling logistics.
```
</details>

---

## Where is my data?

Once configured, the system uses the storage domains defined in
`config/storage_domains.json`. The default layout is:

* **`datasets/startups/<startup>/`**: raw startup data rooms, such as pitch decks, Excel sheets, and PDFs.
* **`datasets/community/<dataset>/`**: community/member datasets, such as `sictic-members`.
* **`registry/persons/<dataset>.md`**: manually maintained person lists.
* **`derived/<dataset>/`**: generated searchable datasets, such as `person-profile`.
* **`insights/startups/<startup>/`** and **`insights/community/<dataset>/`**: generated Markdown reports.
* **`cache/datasets2md/...`**: local parsed Markdown cache generated by Docling.

If you put a pitch deck into `datasets/startups/spacex/`, running the
`startup_profile` skill will parse it, index it, and write the final analysis
to `insights/startups/spacex/`.

Document parsing is handled locally by Docling. On macOS, the installer includes
the `ocrmac` extra for Apple Vision OCR. On Linux/WSL2, the installer uses the
standard Docling package and RapidOCR. In both cases, `DEFAULT_VLM` is used for
image and chart descriptions through Ollama or another configured model provider.

## Google Drive Integration (Production Mode)

By default (`STORAGE_PROVIDER="local"`), all datasets and generated insights are written to the local file system path provided in `STORAGE_PATH`.

In production at SICTIC, we use Google Drive to share datasets and insights with Deal Leads. When `STORAGE_PROVIDER="google"`, the skills read and write directly to Google Drive via the native API.

**Setting up the Google Drive API requires creating an OAuth Desktop-App client in the Google Cloud Console.** Because this process involves navigating complex Google Cloud settings and handling JSON credentials, the best approach is to ask your AI assistant to walk you through the Google Cloud setup and authenticate the credentials for you (We did it with Openclaw)

## Local Google-backed Testing

For local testing with Google credentials, prefer `STORAGE_PROVIDER="hybrid"`. In hybrid mode, Google Drive is used as a read fallback while generated files are written to a local mirror first. Markdown outputs outside local cache paths are then uploaded to Drive as Google Docs; updating an existing Google Doc preserves the file ID and creates a normal Drive revision.

Required `.env` fields for hybrid testing:

```bash
REPO_DIR=/absolute/path/to/SICTIC-AI
STORAGE_PROVIDER=hybrid
STORAGE_PATH=<google-drive-folder-id-root-or-folder-path>
STORAGE_MIRROR_DIR=/absolute/path/to/local-mirror
GDRIVE_CREDENTIALS=/absolute/path/to/credentials.json
GDRIVE_TOKEN=/absolute/path/to/token.json
QDRANT_HOST=http://localhost:6333
OLLAMA_HOST=http://localhost:11434
LLM_MODEL=...
LLM_BASE_URL=...
LLM_API_KEY=...
DEFAULT_VLM=...
EMBEDDING_MODEL=...
EMBEDDING_BASE_URL=...
EMBEDDING_API_KEY=...
```

The default test suite is mocked/local and safe to run with:

```bash
conda run -n sictic-env python -m pytest -q
```

Opt-in live smoke tests require local services and configured storage:

```bash
SICTIC_RUN_LIVE_SMOKE=1 conda run -n sictic-env python -m pytest -q -m live
```
