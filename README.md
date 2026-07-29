# SICTIC-AI

![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)
![License MIT](https://img.shields.io/badge/license-MIT-green.svg)
![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)

SICTIC is Switzerland's largest and most active business angel network. It has already connected 1'000+ early-stage startups with 500+ angel investors ([sictic.ch](https://www.sictic.ch)).

This is the SICTIC-AI toolkit we use. It is an open-source collection of AI-powered analysis routines (also known as skills) designed to supercharge the startup ecosystem. It is completely free to use and easy to contribute to!

This toolkit serves four audiences:
* **Startups:** Prepare for your first funding round with a dry run of our AI on your data room.
* **Business Angels:** Automate common assessments in your Due Diligence process.
* **BA Clubs (like SICTIC):** Automate member engagement, startup selection, DD, and monitoring past transactions.
* **AI Wizards:** Co-develop and refine the future of early stage funding rounds with us!

## Available Skills

| Skill | Status | Description |
|---|---|---|
| **Community** | | |
| `expert_search` | ✅ | Identifies club members with relevant domain expertise for due diligence or operational support |
| `potential_investors` | ✅ | Identifies potential investors for a startup with the strongest fit |
| `advocates` | ✅ | Identifies inspiring members to represent the organization at external events |
| `investor_profile` | ✅ | Combines each member's professional profile with their investment track record and preferences |
| `suggested_startups` | ✅ | Proposes attractive startups in active fundraising to each member |
| **Startup Selection & Jury** | | |
| `submission_ready` | ✅ | Checks whether a Dealum application is complete and meets initial SICTIC eligibility criteria |
| `pitch_ready` | | Evaluates the clarity and completeness of startup materials for investor pitch sessions |
| **Due Diligence** | | |
| `startup_profile` | ✅ | Generates a succinct overview of the startup and serves as input for other skills |
| `team_profile` | ✅ | Assesses individual founders and overall team dynamics |
| `person_profile` | ✅ | Generates a comprehensive profile for any founder, member, or other person in a dataset |
| `startup_traction` | ✅ | Summarizes and quantifies the startup's market traction |
| `dd_checks` | ✅ | Executes a comprehensive suite of common due diligence checks |
| `market_review` | | Analyzes market size, customer needs, competition, and substitutes |
| `t&c_review` | | Reviews and assesses the terms and conditions of a proposed funding round |
| **Ongoing Monitoring** | | |
| `alerts&news` | | Monitors and interprets relevant news and updates concerning portfolio startups |
| `startup_support` | | Coordinates operational support provided to startups by investors |
| `portfolio_mgmt` | | Generates risk-return overviews and performance metrics for startup portfolios |
| **Operations** | | |
| `gdrive_sync` | ✅ | Synchronizes local storage with Google Drive |
| `bulk_refresh` | ✅ | Refreshes one or more insights across one or more datasets |
| `dataset_maintenance` | ✅ | Diagnoses, migrates, prunes, and repairs datasets and Qdrant collections |
| `startup_website_import` | ✅ | Imports startup public websites into dataset website folders |
| `linkedin_maintenance` | ✅ | Lists missing LinkedIn profiles, imports manually scraped profiles, and diagnoses registry issues |


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


## Contributing

The setup is deliberately simple so everyone can join and co-develop:
* This is about investing expertise and insight, not IT know-how.
* You can safely create new skills or edit existing ones directly inside your UI.
* Your AI coding agent can review the changes and use its Git integration to
  publish them to GitHub.

## Runtime Context

The toolkit requires a Unix environment (**macOS, Linux, or WSL2**) and an AI Agent
(like **OpenClaw, Claude Code, Codex, or Gemini Spark**) to converse with the skills.
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

Install **Ollama** if you want to use local `ollama/...` models. Local models
are our default in `.env-template` and are useful for heavy document parsing.
* **macOS:** `brew install ollama`
* **Linux/WSL2:** `curl -fsSL https://ollama.com/install.sh | sh`

Qdrant is required for semantic search. You do not need to install it manually:
`./launch.sh start` downloads the matching Qdrant binary for macOS or Linux into
`./qdrant/` and starts it with local storage in `./qdrant_data/`.

### Step 2: Install the Environment

Run the provided installer. This creates a self-contained Python environment
(`sictic-env`) and copies the skill folder contents into your AI workspace.
The installer registers the repository root in the Conda environment, so
harness commands execute the current repo code. Re-run the installer after
changing skill instructions or adding/removing skills. All runtime dependencies
are defined in `environment.yml`.

```bash
# Same for macOS, Linux, and WSL2
./install.sh
```

The installer creates the conda environment `sictic-env` for macOS, Linux, and
WSL2. `skills.dataset_chat` uses Docling for document ingestion, with:
* Apple Vision OCR through `ocrmac` on macOS.
* RapidOCR on Linux/WSL2.

### Step 3: Configuration

The installer creates `.env` from `.env-template` if needed and prompts for the
runtime values. Press Enter to accept the value shown in brackets. You need to
configure these variables:

| \# | Variable | Purpose | Example |
|---|---|---|---|
|1| `INSTALLED_SKILLS_PATH` | Deployment-only path for installer-copied skills; development happens in `REPO_PATH` | `/Users/you/.openclaw/workspace-ops/skills` |
|2| `REPO_PATH` | Absolute path to the root of this SICTIC-AI git repository | `/Users/you/SICTIC-AI` |
|3| `LOCAL_STORAGE_PATH` | Absolute local application storage path | `/Users/you/SICTIC-AI/gdrive-mirror` |
|4| `LOCAL_DATA_PATH` | Absolute local runtime cache path for `cache/` and `docling_data/` | `/Users/you/SICTIC-AI` |
|5| `CLOUD_PROVIDER` | Optional cloud backend; currently only`google` works | `google` |
|6| `CLOUD_STORAGE_PATH` | Cloud root, such as a Drive folder ID, `root`, or folder path/name | `SICTIC-AI-storage` |
|7| `LLM_MODEL` | The primary text-generation model used for analysis | `google/gemini-flash-latest` or `ollama/qwen3:8b` |
|8| `LLM_BASE_URL` | Base URL for the text-generation endpoint; blank uses the provider default | `http://localhost:11434` |
|9| `LLM_API_KEY` | API key for the text-generation endpoint when needed | blank for local Ollama |
|10| `VLM_MODEL` | The model used for extracting text from images/charts | `ollama/qwen3-vl:8b` or `openai/gpt-4o-mini` |
|11| `VLM_BASE_URL` | Base URL for the vision-language endpoint; defaults to `LLM_BASE_URL` | `http://localhost:11434` |
|12| `VLM_API_KEY` | API key for the vision-language endpoint; defaults to `LLM_API_KEY` | blank for local Ollama |
|13| `EMBEDDING_MODEL` | The model used for semantic search embeddings | `ollama/qwen3-embedding:8b` or `openai/text-embedding-3-small` |
|14| `EMBEDDING_BASE_URL` | Base URL for the embedding endpoint; blank uses the provider default | `http://localhost:11434` |
|15| `EMBEDDING_API_KEY` | API key for the embedding endpoint when needed | blank for local Ollama |
|16| `RANKED_LLMS` | If insights md files were created with several models, the preferred ranking for re-use. (CSV list) | see `.env-template` |

*(Note: The other variables in `.env-template` are explained inline. You don't need to change them).*

`REPO_PATH` points to this git repository. `INSTALLED_SKILLS_PATH` points to
the installed skill-copy directory used by the AI workspace for skill discovery.
Legacy aliases such as `REPO_DIR`, `WORKSPACE_PATH`, `WORKSPACE_DIR`, `STORAGE_PROVIDER`,
`STORAGE_PATH`, and `STORAGE_MIRROR_PATH` are no longer used; the installer
removes them from `.env` when it runs.

### Step 4: Start Background Services

SICTIC-AI relies on Qdrant for semantic search and on Ollama when any configured
model starts with `ollama/`. The launcher downloads Qdrant when needed, starts
Qdrant and Ollama, and pulls the Ollama models referenced by `LLM_MODEL`,
`EMBEDDING_MODEL`, and `VLM_MODEL` if they are not already available.

```bash
./launch.sh start
./launch.sh status  # check running services
./launch.sh stop    # shut down local background services
```

### Step 5: Run a Skill

You are ready to go. There are two common ways to execute skills:

1. Use the lightweight slash-command harness for user-facing commands exposed by
   `skills.harness`.
2. Run a skill module directly when you need that module's own CLI options or
   when the command is an operational utility.

```bash
conda run -n sictic-env python -m skills.harness /startup_profile SpaceX
conda run -n sictic-env python -m skills.dataset_chat SpaceX "What are the main risks?"
```

The harness also has an interactive mode. When launching it through
`conda run`, use `--no-capture-output`; otherwise Conda may close stdin and the
prompt exits immediately.

```bash
conda run -n sictic-env --no-capture-output python -m skills.harness
```

Alternatively, activate the environment first and then run:

```bash
conda activate sictic-env
python -m skills.harness
```

Inside the harness, run `/help` to list commands such as
`/dataset_chat <dataset> <question>`, `/startup_profile <startup>`, and
`/dd_checks <startup>`.

### Command interfaces

Use these supported entry points:

| Interface | Purpose | Example |
|---|---|---|
| Harness one-shot | Run one user-facing slash command and exit | `conda run -n sictic-env python -m skills.harness /startup_profile SpaceX` |
| Harness interactive | Start the slash-command REPL for manual testing | `conda run -n sictic-env --no-capture-output python -m skills.harness` |
| Skill module | Run one module's direct CLI and options | `conda run -n sictic-env python -m skills.bulk_refresh --dataset spacex --skill startup_profile` |
| Dataset maintenance | Maintained operational utility | `conda run -n sictic-env python -m skills.dataset_maintenance from-insight --insight investor_profile --source-dataset sictic-members` |
| Script | Maintenance or migration operation documented by that script | `conda run -n sictic-env python scripts/generate_member_profiles.py --help` |

Use the harness when the command exists in `/help` and you want the stable,
user-facing behavior. Harness commands always start with `/`, for example
`/startup_profile SpaceX`; plain `startup_profile SpaceX` is rejected.

Use direct module execution as `python -m skills.<skill_name>` when the skill has
its own CLI flags, when it is not exposed by `/help`, or when the operation is a
batch or maintenance workflow. For example, `skills.bulk_refresh` is usually run
directly because its module CLI owns options such as `--dataset` and `--skill`.

## Using it in practice

### 1. Community management

Communities can be large, so it is useful to do some preparation overnight.

To make an inventory of all persons mentioned in `community/sictic-members/datasets/`, run:

```bash
conda run -n sictic-env python -c "from skills.person_profile.persons_in_dataset import persons_in_dataset; persons_in_dataset('sictic-members')"
```

It will generate a draft of all members in `community/sictic-members/insights/persons-in-dataset-sictic-members-manual.md`. Probably it is quite incomplete and you want to edit it manually. From there on, the system will use that list of members.

Next you want to create a comprehensive profile of each member combining their LinkedIn profile, their resumes and other credentials. For this you use:

```bash
conda run -n sictic-env python -m skills.person_profile --dataset sictic-members
```

The resulting profiles are in:

```text
storage/community/sictic-members/insights/person-profile/
```

It may report LinkedIn profiles that require manual scraping. Use:

```bash
python -m skills.linkedin_maintenance missing
python -m skills.linkedin_maintenance import profiles.json
python -m skills.linkedin_maintenance diagnose
```

The import command uses the pending registry to route each profile to its
dataset. An explicit `--dataset` may be supplied as an additional target.

The matching skills `expert_search`, `potential_investors`, and `advocates`
search a derived `sictic-members-investor-profile` dataset for the best fit. Its
documents combine professional profiles with investment track records and
preferences.

```bash
conda run -n sictic-env python -m skills.investor_profile
conda run -n sictic-env python -m skills.dataset_maintenance from-insight --insight investor_profile --source-dataset sictic-members
```

### 2. Overnight Refresh

The `bulk_refresh` command can refresh a set of insights on a set of datasets.
* If the datasets are not specified, it will refresh all skills with a `__active_dataset__.md` file in the dataset subfolder.
* If the insights are not specified, it will refresh all relevant skills.

```bash
# refresh the person_profile on spacex
conda run -n sictic-env python -m skills.bulk_refresh --skill person_profile --dataset spacex
# refresh all insights on spacex
conda run -n sictic-env python -m skills.bulk_refresh --dataset spacex
# refresh all the person_profile for all active dataset
conda run -n sictic-env python -m skills.bulk_refresh --skill person_profile
# refresh all insights on all active dataset
conda run -n sictic-env python -m skills.bulk_refresh

```

## Where is my data?

Once configured, the system uses the storage domains defined in
`config/storage_domains.json`. The default layout is:

| Path | Description |
|---|---|
| `storage/startups/<startup>/datasets/` | Raw startup data rooms, such as pitch decks, Excel sheets, and PDFs. |
| `storage/startups/<startup>/insights/` | Generated startup Markdown reports. |
| `storage/community/<dataset>/datasets/` | Primary community and member datasets, such as `sictic-members`. |
| `storage/community/<dataset>/insights/` | Generated community Markdown reports and profiles. |
| `storage/generated/<dataset>/datasets/` | Searchable datasets assembled from insights, such as `sictic-members-investor-profile`. |
| `storage/generated/<dataset>/insights/` | Insights associated with generated datasets, when applicable. |
| `docling_data/datasets2md/<domain>/<dataset>/datasets/` | Durable machine-local parsed Markdown generated by Docling. This is not synchronized to Google Drive. |
| `storage/<domain>/<dataset>/insights/persons-in-dataset-<dataset>-manual.md` | Manually maintained person lists generated by `persons_in_dataset`. |
| `gdrive_sync_state/<pairing-id>/` | Durable Google Drive synchronization baseline and changes token. Do not delete this as part of cache cleanup. |
| `cache/...` | Disposable runtime cache and temporary operational state. |

`LOCAL_DATA_PATH` optionally changes the root containing `cache/` and
`docling_data/`. It defaults to `REPO_PATH`.

If you put a pitch deck into `storage/startups/spacex/datasets/`, running the
`startup_profile` skill will parse it, index it, and write the final analysis
to `storage/startups/spacex/insights/`.

Document parsing is handled locally by Docling. On macOS, the installer includes
the `ocrmac` extra for Apple Vision OCR. On Linux/WSL2, the installer uses the
standard Docling package and RapidOCR. In both cases, `VLM_MODEL` is used for
image and chart descriptions through Ollama or another configured model provider.
RTF files, which Docling does not support, are converted directly to searchable
plain text using the Conda `striprtf` package.

## Test suite

Run the local test suite with:

```bash
conda run -n sictic-env python -m pytest -q
```

The default suite uses isolated local storage and mocked external services.
Tests marked `live` are collected but skipped.

To run only the opt-in live tests:

```bash
SICTIC_RUN_LIVE_SMOKE=1 conda run -n sictic-env python -m pytest -q -m live
```

Live tests may require running Qdrant and Ollama services and specific test
datasets. Tests whose required datasets are unavailable are skipped.

## Google Drive Integration

All skills read and write the local filesystem path configured by
`LOCAL_STORAGE_PATH`. Google Drive access is isolated in the standalone
`gdrive_sync` administrative utility under `gdrive-sync/`; normal application
storage never accesses Drive.

In production at SICTIC, Google Drive is used to share datasets and insights
with Deal Leads. `CLOUD_PROVIDER=google` enables synchronization and
`CLOUD_STORAGE_PATH` identifies the Drive root.

**Setting up the Google Drive API requires creating an OAuth Desktop-App client in the Google Cloud Console.** Because this process involves navigating complex Google Cloud settings and handling JSON credentials, the best approach is to ask your AI assistant to walk you through the Google Cloud setup and authenticate the credentials for you (We did it with Openclaw)

#### Google Drive Synchronization

Synchronizing a large cloud drive is tedious and slow. SICTIC-AI therefore
works entirely against `LOCAL_STORAGE_PATH`, tracks changes on both sides, and
synchronizes periodically instead of accessing Google Drive for every file
operation.

| Command | Description |
|---|---|
| `python -m gdrive_sync pull` | Make local storage match Google Drive. Cloud is authoritative. Use this to create the initial local copy and synchronization baseline. |
| `python -m gdrive_sync sync --conflict-policy local-wins` | Synchronize changes in both directions. If the same path changed on both sides, keep the local version as canonical. |
| `python -m gdrive_sync sync --conflict-policy cloud-wins` | Merge cloud changes into local storage. Cloud adds and updates overwrite or create local files. Nothing is deleted on either side. |

Add `--dry-run` to any command to report the planned changes without modifying
local files, Google Drive, or the successful synchronization baseline. Add
`--json` when machine-readable output is useful.

Google Drive shortcuts are not supported inside the synchronized root.
Synchronization preflights for shortcuts and stops before applying changes;
replace any shortcut with a real folder or file before retrying.

The normal routine is:

1. **Initial setup:** run `python -m gdrive_sync pull`. The first pull
   walks the complete Drive tree and builds the baseline, so it can take
   substantial time. (read: hours)
2. **Before a job:** run
   `python -m gdrive_sync sync --conflict-policy cloud-wins`. This downloads
   cloud adds and updates locally without deleting files on either side.
3. **Run the job:** skills read and write only `LOCAL_STORAGE_PATH`; they do not
   synchronize while the job is running.
4. **After a job:** run
   `python -m gdrive_sync sync --conflict-policy local-wins`.

Later synchronizations are faster because `gdrive_sync` compares local hashes
with its stored baseline and uses the Google Drive Changes API instead of
rebuilding the complete inventory each time.

Synchronization is manual today. Automatic synchronization around skill jobs
is planned but has not yet been implemented.

The command reads these `.env` values:

* `CLOUD_PROVIDER`: must be `google`
* `LOCAL_STORAGE_PATH`: local application storage root
* `CLOUD_STORAGE_PATH`: Google Drive folder ID/root
* `GDRIVE_CREDENTIALS`: OAuth Desktop-App credentials JSON
* `GDRIVE_TOKEN`: cached OAuth token JSON

Configuring Google OAuth and Drive access is outside the scope of this README.
Ask a chatbot for help; Gemini was used to configure the current installation.

The durable baseline and Drive changes token are stored under
`gdrive_sync_state/<pairing-id>/`. Do not delete this directory as cache.
Runtime logs are written to `logs/gdrive-sync.log`.

## Dataset Maintenance

Dataset ingestion owns document replacement and removal decisions. Qdrant
adapters perform database operations only. Collection diagnostics and pruning
are exposed separately:

```bash
python -m skills.dataset_maintenance diagnose
python -m skills.dataset_maintenance prune
python -m skills.dataset_maintenance prune --apply
python -m skills.dataset_maintenance migrate-startup-dossiers
```

Pruning is dry-run by default.
