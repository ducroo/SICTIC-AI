# SICTIC-AI

Welcome to the SICTIC-AI toolbox! This is an open-source collection of AI-powered analysis routines (skills)
designed to supercharge the startup ecosystem. It is completely free to use and easy to contribute to! 

This toolbox serves four distinct audiences:
* **Startups:** Prepare for your first funding round by running our AI over your data room for a dry run.
* **Business Angels:** Automate the heavy lifting and boilerplate checks of your Due Diligence process.
* **BA Clubs (like SICTIC):** Automate member engagement, startup selection, DD, and monitor past transactions.
* **AI Wizards:** Co-develop and refine the future of AI-first funding rounds with us.

## Runtime Context

This toolbox requires a Unix environment (**macOS, Linux, or WSL2**) and an AI harness 
(like **OpenClaw, Claude Code, or Gemini Spark**) to converse with the skills. 
We primarily develop using macOS and OpenClaw, but the architecture is strictly OS-agnostic!

## Quickstart Setup

Just a few simple steps to get the AI working on your machine:

### Step 1: Install Prerequisites

You need a package manager and Conda to handle the Python environment. We strongly recommend Miniforge.

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
You can optionally install **Ollama** if you want to run local AI models. Local models are highly 
recommended, as cloud models can become expensive during heavy document parsing.
* **macOS:** `brew install ollama`
* **Linux/WSL2:** `curl -fsSL https://ollama.com/install.sh | sh`

### Step 2: Install the Environment

Run the provided installer. This safely creates a self-contained Python environment (`sictic-env`) 
and strictly synchronizes the AI skills with your workspace using symlinks.

```bash
./install_skills_conda.sh --target /path/to/your/harness/workspace/skills
```

### Step 3: Configuration

Create your configuration file:
```bash
cp .env-template .env
```

Open `.env` in a text editor. You only need to configure the following core variables:

| Variable | Purpose | Example |
|---|---|---|
| `WORKSPACE_DIR` | Absolute path to the AI workspace skills directory | `/Users/you/.openclaw/workspace-ops/skills` |
| `STORAGE_PROVIDER` | Where should data be saved? (`local` or `google`) | `local` |
| `STORAGE_PATH` | If `local`: absolute path. If `google`: Folder ID or `root` | `/Users/you/sictic_data` or `root` |
| `DEFAULT_LLM` | The primary model used for analysis | `google/gemini-flash-latest` |
| `DEFAULT_VLM` | The model used for extracting text from images/charts | `ollama/qwen3-vl:8b` |
| `DEFAULT_EMBEDDINGS` | The model used for semantic search | `ollama/qwen3-embedding:8b` |
| `RANKED_LLMS` | Fallback models if the default fails (CSV list) | see `.env-template` |

*(Note: The `.env-template` contains several other advanced variables for concurrency limits and caching. These are all explained inline and can be left at their defaults).*

### Step 4: Start Backing Services

SICTIC-AI relies on a local vector database (Qdrant) to remember documents. The universal launcher script 
automatically downloads and manages the correct binary for your OS in the background. 

*(Note: If you installed Ollama in Step 1, the launcher will also automatically pin it up so you can run local models!)*

```bash
./launch.sh start
```

### Step 5: Run a Skill

You are ready to go! Skills can be executed universally without needing to manually activate virtual environments.

```bash
conda run -n sictic-env python -m skills.llm_chat "What is startup due diligence?"
conda run -n sictic-env python -m skills.startup_profile --startup "DAAV"
```

---

## Google Drive Integration (Production Mode)

By default (`STORAGE_PROVIDER="local"`), all datasets and generated insights are written to the local file system path provided in `STORAGE_PATH`.

In production at SICTIC, we use Google Drive to seamlessly share datasets and insights with Deal Leads. When `STORAGE_PROVIDER="google"`, the skills read and write directly to Google Drive via the native API.

**Setting up the Google Drive API requires creating an OAuth Desktop-App client in the Google Cloud Console.** Because this process involves navigating complex Google Cloud settings and handling JSON credentials, the best approach is to address that directly with your chosen AI harness (e.g., OpenClaw). Just ask your AI assistant to walk you through the Google Cloud setup and authenticate the credentials for you!

## Contributing

Because the workspace is symlinked directly to the repository, you can safely create new skills or edit existing ones directly inside your UI.

To synchronize your changes with GitHub without using the terminal, simply trigger the `sictic_git_sync` skill. The AI will act as an architectural gatekeeper—reviewing your code, enforcing our simplicity standards, and automatically committing and pushing your updates to GitHub.

