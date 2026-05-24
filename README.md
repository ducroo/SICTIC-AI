# SICTIC-AI

![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)
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
| **Community** | `expert_search` | ✅ | Identifies club members with relevant domain expertise to assist with due diligence or operational support |
| | `potential_investors` | ✅ | Identifies potential investors for a startup |
| | `advocates` | ✅ | Identifies inspiring members to represent the organization at external events |
| | `investment_appetite` | ✅ | Articulates and maps the specific investment sweet spot and thesis for each member |
| | `suggested_startups` | ✅ |  Proposes 5–7 attractive startups in active fundraising to each members |

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
sudo apt update && sudo apt install wget
wget "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"
bash Miniforge3-*.sh  # Follow the prompts, say 'yes' to init
exec $SHELL           # reload your terminal
```

*(Optional but Recommended)*
You can install **Ollama** to run local AI models, as cloud models can become expensive during heavy document parsing.
* **macOS:** `brew install ollama`
* **Linux/WSL2:** `curl -fsSL https://ollama.com/install.sh | sh`

### Step 2: Install the Environment

Run the provided installer. This creates a self-contained Python environment (`sictic-env`) 
and inserts the toolkit in your workspace using **symlinks**.

```bash
./install_skills_conda.sh --target /Users/you/.openclaw/workspace-ops/skills
```

### Step 3: Configuration

Create your configuration file:
```bash
cp .env-template .env
```

Open `.env` in a text editor. You need to configure seven variables:

| \# | Variable | Purpose | Example |
|---|---|---|---|
|1| `WORKSPACE_DIR` | Absolute path to the AI workspace skills directory | `/Users/you/.openclaw/workspace-ops/skills` |
|2| `STORAGE_PROVIDER` | Where should data be saved? (`local` or `google`) | `local` |
|3| `STORAGE_PATH` | If `local`: absolute path. If `google`: Folder ID or `root` | `/Users/you/sictic_data` or `root` |
|4| `DEFAULT_LLM` | The primary model used for analysis | `google/gemini-flash-latest` |
|5| `DEFAULT_VLM` | The model used for extracting text from images/charts | `ollama/qwen3-vl:8b` or `openai/gpt-4o-mini` |
|6| `DEFAULT_EMBEDDINGS` | The model used for semantic search | `ollama/qwen3-embedding:8b` or `openai/text-embedding-3-small` |
|7| `RANKED_LLMS` | If insights md files were created with several models, the preferred ranking for re-use. (CSV list) | see `.env-template` |

*(Note: The other variables in `.env-template` are explained inline. You don't need to change them).*

### Step 4: Start Background Services

SICTIC-AI relies on a local vector database (Qdrant) for semantic search (i.e. pre-selection of documents before handing over to the LLM). The launcher script will install the right binary if needed. If you installed Ollama in Step 1, the launcher will spin it up so you can run local models.

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

