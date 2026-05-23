# SICTIC-AI

![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)
![License MIT](https://img.shields.io/badge/license-MIT-green.svg)
![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)

Welcome to the SICTIC-AI toolkit! This is an open-source collection of AI-powered analysis routines (skills)
designed to supercharge the startup ecosystem. It is completely free to use and easy to contribute to! 

This toolbox serves four audiences:
* **Startups:** Prepare for your first funding round by running our AI over your data room for a dry run.
* **Business Angels:** Automate the heavy lifting and boilerplate checks of your Due Diligence process.
* **BA Clubs (like SICTIC):** Automate member engagement, startup selection, DD, and monitor past transactions.
* **AI Wizards:** Co-develop and refine the future of AI-first funding rounds with us!

## Contributing

The setup is deliberately simple so everyone can join and co-develop:
* We invite you to contribute investing expertise and insight, not IT know-how.
* You can safely create new skills or edit existing ones directly inside your UI. 
* To synchronize your changes with GitHub, just ask your AI agent to help; it has a  `sictic_git_sync` skill. This skill will also act as an architectural gatekeeper—reviewing your code, enforcing our simplicity standards, and automatically committing and pushing your updates to GitHub.

## Runtime Context

This toolbox requires a Unix environment (**macOS, Linux, or WSL2**) and an AI Agent 
(like **OpenClaw, Claude Code, or Gemini Spark**) to converse with the skills. 
We primarily develop using macOS and OpenClaw, but the architecture has to become OS-agnostic.

## Quickstart Setup

Five steps to get the AI working on your machine:

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
sudo apt update && sudo apt install wget
wget "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"
bash Miniforge3-*.sh  # Follow the prompts, say 'yes' to init
exec $SHELL           # reload your terminal
```

*(Optional but Recommended)*
You can install **Ollama** if you want to run local AI models; Local models are a good alternative, as cloud models can become expensive during heavy document parsing.
* **macOS:** `brew install ollama`
* **Linux/WSL2:** `curl -fsSL https://ollama.com/install.sh | sh`

### Step 2: Install the Environment

Run the provided installer. This creates a self-contained Python environment (`sictic-env`) 
and synchronizes the AI skills with your workspace using **symlinks**.

```bash
./install_skills_conda.sh --target /Users/you/.openclaw/workspace-ops/skills
```

### Step 3: Configuration

Create your configuration file:
```bash
cp .env-template .env
```

Open `.env` in a text editor. You need to configure a few variables:

| Variable | Purpose | Example |
|---|---|---|
| `WORKSPACE_DIR` | Absolute path to the AI workspace skills directory | `/Users/you/.openclaw/workspace-ops/skills` |
| `STORAGE_PROVIDER` | Where should data be saved? (`local` or `google`) | `local` |
| `STORAGE_PATH` | If `local`: absolute path. If `google`: Folder ID or `root` | `/Users/you/sictic_data` or `root` |
| `DEFAULT_LLM` | The primary model used for analysis | `google/gemini-flash-latest` |
| `DEFAULT_VLM` | The model used for extracting text from images/charts | `ollama/qwen3-vl:8b` or `openai/gpt-4o-mini` |
| `DEFAULT_EMBEDDINGS` | The model used for semantic search | `ollama/qwen3-embedding:8b` or `openai/text-embedding-3-small` |
| `RANKED_LLMS` | If insights md files were created with several models, the preferred ranking for re-use. (CSV list) | see `.env-template` |

*(Note: The `.env-template` contains several other variables that can be left at their defaults. Still, they are explained inline).*

### Step 4: Start Background Services

SICTIC-AI relies on a local vector database (Qdrant) for semantic search (i.e. pre-selection of documents before handing over to the LLM). The launcher script will also install the right binary if needed. If you installed Ollama in Step 1, the launcher will also spin it up so you can run local models.

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

Once configured, the system uses two main folders under your `STORAGE_PATH`:
* **`datasets/<dataset_name>/`**: This is where you (or the startup) drop raw files (Pitch Decks, Excel sheets, PDFs).
* **`insights/<dataset_name>/`**: This is where the AI outputs its finished Markdown reports. 

If you put a pitch deck into `datasets/spacex/`, running the `startup_profile` skill will automatically parse it, read it, and drop the final analysis into `insights/spacex/`.

## Google Drive Integration (Production Mode)

By default (`STORAGE_PROVIDER="local"`), all datasets and generated insights are written to the local file system path provided in `STORAGE_PATH`.

In production at SICTIC, we use Google Drive to share datasets and insights with Deal Leads. When `STORAGE_PROVIDER="google"`, the skills read and write directly to Google Drive via the native API.

**Setting up the Google Drive API requires creating an OAuth Desktop-App client in the Google Cloud Console.** Because this process involves navigating complex Google Cloud settings and handling JSON credentials, the best approach is to ask your AI assistant to walk you through the Google Cloud setup and authenticate the credentials for you (We did it with Openclaw)

