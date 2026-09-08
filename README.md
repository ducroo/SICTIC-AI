# Make your AI agent smarter at startup investing

![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)
![License MIT](https://img.shields.io/badge/license-MIT-green.svg)
![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)

SICTIC-AI works inside the AI agent you already use, such as Codex, Claude Code
or Cowork, OpenClaw, or Gemini. It gives your agent reusable **skills** for
startup analysis, due diligence, investor matching, and angel-network operations. The
important checks and workflows are codified up front, so your agent can apply
them consistently instead of inventing an approach on the spot.

To set it up, ask your agent to install this repository. It can inspect your
machine, install the required local services, configure the toolkit, and verify
the result. A ready-to-use installation prompt is provided below.

Once installed, run a skill by asking naturally: “Run `startup_profile` for
SpaceX” or “Ask the `spacex` dataset about its main technical risks.” Your agent
reads the relevant skill instructions, runs the workflow, and returns the
result with its supporting evidence.

## Built from real angel-investing workflows

SICTIC is Switzerland's largest and most active angel investor network. It
brings together more than 500 investors, has hosted more than 1,000 startup
pitches, and its investor community has helped fund more than 300 Swiss
technology startups ([sictic.ch](https://www.sictic.ch)). SICTIC-AI turns that
practical experience into an open-source toolkit that is free to use and
contribute to.

It helps:

- **Startups:** Review funding materials before approaching investors.
- **Business angels:** Accelerate common due-diligence assessments.
- **Angel investor networks:** Support member engagement, startup selection,
  due diligence, and portfolio monitoring.
- **Contributors:** Improve how AI supports early-stage funding by extending
  shared, reviewable workflows.

Recent releases also add hybrid semantic and keyword retrieval, table-aware
spreadsheet ingestion, safer Qdrant lifecycle management, and dependency-aware
bulk refreshes.

## Install with your AI agent

Start your agent and send it this prompt:

```text
Install SICTIC-AI for me using its default local setup.

Before running commands, ask me exactly one question:
“Which exact local folder should contain the SICTIC-AI repository?
For example: /Users/you/SICTIC-AI”

After the initial folder question, ask me again only if:
- the selected folder cannot be used safely;
- installing a system prerequisite requires my authorization;
- the operating system cannot support the default setup; or
- setup fails and there are multiple materially different ways to proceed.

Do not configure Google Drive synchronization, hosted model providers, API
keys, or other optional integrations. Mention them only after the local
installation succeeds.

After I answer, continue autonomously:

1. Check whether the operating system is macOS, Linux, or WSL2.
2. Check the tools needed to clone the repository:
   - on macOS, first check whether Homebrew is installed, then check Git;
     install either one if missing
   - on Ubuntu, Debian, or WSL2, check Git, curl, and wget; install any that are
     missing using apt
3. Clone https://github.com/ducroo/SICTIC-AI into the folder I selected. If
   that folder already contains the correct repository, reuse it after
   verifying its Git remote. Never overwrite an unrelated or modified folder.
4. Read README.md and follow its “Manual setup” section in sequence.
5. Check for Miniforge/Conda and Ollama. Install either one if missing using the
   documented platform commands.
6. Run the installer without copying skills to an agent skills directory, using
   these defaults:
   - REPO_PATH: the selected repository folder
   - LOCAL_STORAGE_PATH: <REPO_PATH>/local_storage
   - LOCAL_DATA_PATH: <REPO_PATH>
   - accept the installer's default local models, URLs, and service settings
7. Start Ollama and Qdrant with ./launch.sh start and confirm that both services
   are running. Allow the launcher to pull configured Ollama models that are
   missing, but do not delete or reinstall models that are already present.
8. Run the test suite and the skill harness help command to verify the setup.
9. Report what was installed, the important paths, and one example command for
   running a user-facing skill.

Do not modify tracked repository source files as part of installation.
```

This prompt deliberately installs local models, so it does not require an API
account or send startup data to a hosted LLM provider.

### Switching models

The bundled local models make the default installation widely accessible, but
more capable models are available if your hardware or budget permits. Local
options include the [Gemma 4](https://ollama.com/library/gemma4) and
[Qwen 3.6](https://ollama.com/library/qwen3.6) families through Ollama; cloud
options include `gpt-5.6-luna` through the OpenAI API. Larger local models
generally require substantially more memory and disk space.

The example below switches text generation to OpenAI while retaining the local
vision and embedding models. Other local models and cloud providers follow a
similar route: select the model and configure its endpoint and API key when
required.

To use `gpt-5.6-luna`:

1. Create an account at [platform.openai.com](https://platform.openai.com/),
   configure billing, and create an
   [API key](https://platform.openai.com/api-keys).
2. Replace these values in `.env`:

```dotenv
LLM_MODEL=openai/gpt-5.6-luna
LLM_BASE_URL=
LLM_API_KEY=your-api-key
```

Treat the API key like a password: never commit or share your `.env` file. The
model name and API-key workflow are documented in the
[official OpenAI model documentation](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
and [API quickstart](https://platform.openai.com/docs/quickstart).

## Contributing

Read [AGENTS.md](AGENTS.md) for working procedures and the
[standards skill](skills/standards_and_architecture/SKILL.md) for technical
contracts. Each skill's `SKILL.md` describes its own workflow; prompts and
assessment criteria live in `config/`.

By establishing shared standards for
early-stage investing, we aim to structurally strengthen the startup ecosystem
in Switzerland and Europe.

Join us with your experience, questions, and ideas! Critical thinking and practical investing experience are the differentiators; We already have the AI wizards in the team.

We develop skills in teams and meet regularly to challenge assumptions, compare
results, and improve the workflows. Help us turn strong investing practice into open, reusable skills.

## Manual setup

SICTIC-AI requires macOS, Linux, or WSL2, plus Git, Miniforge, and Ollama.
Ollama is required for the default local models. Install the prerequisites for
your platform first.

On macOS:

```bash
# Install Homebrew first if `brew` is not available:
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install --cask miniforge
conda init zsh
exec $SHELL
brew install ollama
```

On Ubuntu, Debian, or WSL2:

```bash
sudo apt update && sudo apt install -y git curl wget
wget "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"
bash Miniforge3-*.sh
conda init bash
exec $SHELL
curl -fsSL https://ollama.com/install.sh | sh
```

Then clone the repository and run the installer:

```bash
git clone https://github.com/ducroo/SICTIC-AI.git
cd SICTIC-AI
./install.sh
./launch.sh start
./launch.sh status
```

The installer creates or updates the `sictic-env` Conda environment and helps
configure `.env`. It also asks for `INSTALLED_SKILLS_PATH`: the optional
directory into which it copies skills for discovery by your AI agent.

- Choose `none` to work directly from the repository without copying skills.
- Enter an absolute path to make SICTIC-AI skills discoverable by that agent.

For the default local setup:

- Set `REPO_PATH` to `/Users/you/SICTIC-AI`, replacing it with the folder where
  you put the repository.
- Accept the suggested local storage and data paths.
- Choose `none` for `INSTALLED_SKILLS_PATH`.
- Accept the local Ollama model, URL, and service defaults.

The installer writes these choices to `.env`.

Repository-only mode still supports all commands documented below. Re-run the
installer after editing or adding skill instructions if you use copied skills.

The commands above are sufficient for the default local setup. For hosted model
providers, advanced command interfaces, and maintenance tasks, see
[Installation and operations](docs/installation-and-operations.md).

## Configuration paths

The installer suggests sensible values for a new `.env`:

| Variable | What it controls | Example |
|---|---|---|
| `REPO_PATH` | Root of this Git repository and its source code | `/Users/you/SICTIC-AI` |
| `INSTALLED_SKILLS_PATH` | Optional directory receiving agent-discoverable copies of skills | `none` or `/Users/you/.claude/skills` |
| `LOCAL_STORAGE_PATH` | Local root containing startup, community, and generated datasets and insights | `/Users/you/SICTIC-AI/local_storage` |
| `LOCAL_DATA_PATH` | Machine-local root under which `cache/` and `docling_data/` are stored | `/Users/you/SICTIC-AI` |

All skills operate on `LOCAL_STORAGE_PATH`. Optional Google Drive
synchronization is independent of the toolkit runtime and is not configured by
`install.sh`. Model and service variables are explained in `.env-template` and
in the [operations guide](docs/installation-and-operations.md).

## Running a skill

Ask your AI agent, or use the command harness directly:

```bash
conda run -n sictic-env python -m skills.harness /startup_profile SpaceX

conda run -n sictic-env python -m skills.harness /dataset_chat SpaceX "What are the main risks?"

conda run -n sictic-env --no-capture-output python -m skills.harness
```

Run `/help` in the interactive harness to see available commands. Some
administrative skills use their own `python -m skills.<name>` interface; their
`SKILL.md` files and the operations guide show the supported syntax.

## User-facing skills

✅ means available. 🚧 means work in progress. ◻️ means planned but not started.
Internal building blocks are intentionally omitted.

| Skill | Status | Description |
|---|---|---|
| **Community** | | |
| `expert_search` | ✅ | Finds members with relevant domain expertise for due diligence or operational support. |
| `potential_investors` | ✅ | Finds investors with the strongest fit for a startup. |
| `advocates` | ✅ | Finds members suited to representing the organization at external events. |
| `investor_profile` | ✅ | Combines a member's professional profile, investment record, and preferences. |
| `suggested_startups` | ✅ | Ranks selected stored startup profiles for each investor; default dataset selection does not verify fundraising status. |
| **Startup selection and jury** | | |
| `submission_ready` | 🚧 | Checks whether a Dealum application is complete and meets initial eligibility criteria. |
| `pitch_ready` | 🚧 | Assesses whether a startup is mature enough and ready to pitch at a SICTIC event. |
| **Due diligence** | | |
| `dataset_chat` | ✅ | Answers evidence-based questions about a startup or community dataset. |
| `startup_profile` | ✅ | Produces a concise, neutral overview used by other skills. |
| `team_profile` | ✅ | Assesses founders and the overall team. |
| `person_profile` | ✅ | Creates a comprehensive profile of a founder, member, or other person. |
| `startup_traction` | ✅ | Summarizes and quantifies commercial traction. |
| `dd_checks` | ✅ | Runs a broad suite of due-diligence checks. |
| `dd_priorities` | ✅ | Synthesizes up to eight decision-relevant priorities from a saved `dd_checks` report. |
| `startup_website_import` | ✅ | Imports a startup's public website into its due-diligence dataset. |
| `market_review` | ◻️ | Reviews market size, customer needs, competition, and substitutes. |
| `sha_review` | 🚧 | Reviews a selected Shareholders' Agreement against a reference SHA and legal checklists. |
| `captable_build` | ✅ | Extracts, assesses, and validates a startup's cap table and convertible loans into a versioned snapshot (see [docs/captable.md](docs/captable.md)). |
| `captable_analysis` | ✅ | Computes conversion scenarios, stamp duty, and red-flag analysis over a stored cap-table snapshot; renders a visual one-pager. |
| `companyresearch.ch` | 🚧 | Uses the companyresearch.ch API to collect publicly available information about a startup. |
| **Ongoing monitoring** | | |
| `alerts_and_news` | ◻️ | Monitors and interprets relevant portfolio-company news and updates. |
| `startup_support` | ◻️ | Coordinates operational support from investors. |
| `portfolio_mgmt` | ◻️ | Produces portfolio risk, return, and performance overviews. |
| **Data and operations** | | |
| `dealum_import` | ✅ | Imports the application dossier of a startup from the Dealum.com platform using an API key. |
| `bulk_refresh` | ✅ | Refreshes selected insights across selected datasets. |
| `dataset_maintenance` | ✅ | Diagnoses, migrates, prunes, and repairs datasets and search indexes. |
| `linkedin_maintenance` | ✅ | Finds missing LinkedIn profiles and imports manually collected profiles. |

## Where is my data?

Application data is rooted at `LOCAL_STORAGE_PATH`; durable parsed documents
and disposable runtime data are rooted at `LOCAL_DATA_PATH`.

| Path | Description |
|---|---|
| **`<LOCAL_STORAGE_PATH>/storage/startups/<startup_name>/`** | **The collection of information about a single startup.** |
| ↳ `./datasets/` | Startup data room: pitch decks, spreadsheets, PDFs, website imports, and other source material. |
| ↳ `./insights/` | Generated startup reports. |
| **`<LOCAL_STORAGE_PATH>/storage/community/<community_name>/`** | **A community or member collection, such as `sictic-members`.** |
| ↳ `./datasets/` | Community and member source data. |
| ↳ `./insights/` | Generated community reports and profiles. |
| **`<LOCAL_STORAGE_PATH>/storage/generated/<dataset_name>/`** | **A searchable dataset assembled from generated insights.** |
| ↳ `./datasets/` | Materialized source documents for the generated dataset. |
| ↳ `./insights/` | Reports associated with the generated dataset. |
| **`<LOCAL_DATA_PATH>/`** | **Machine-local parsed data and disposable runtime data.** |
| ↳ `./docling_data/` | Durable parsed documents; not synchronized to cloud storage. |
| ↳ `./cache/` | Disposable runtime cache and temporary state. |
| ↳ `./cache/scheduler.json` | Shared concurrency state for model and Docling jobs. |

For example, place a pitch deck in
`<LOCAL_STORAGE_PATH>/storage/startups/spacex/datasets/`. Running
`startup_profile` writes its result below
`<LOCAL_STORAGE_PATH>/storage/startups/spacex/insights/`.

## Where to learn more

The `docs/` folder currently contains:

- [Installation and operations](docs/installation-and-operations.md): detailed
  installer modes, environment and model configuration, background services,
  command interfaces, retrieval, maintenance, and tests.
- [Codebase assessment](docs/codebase-assessment.md): a historical architecture
  review; use current standards and skill documents for implementation contracts.

## Optional Google Drive synchronization

The toolkit itself always reads and writes local files. If you want to share
the application-storage tree through Google Drive, the optional `rclone-sync`
helper provides guarded bidirectional synchronization while converting local
Markdown files to native Google Docs and exporting Google Docs back to
Markdown.

Cloud access is deliberately user-owned. Install `rclone`, create and
authenticate your Google Drive remote with `rclone config`, and then run the
guided repository setup:

```bash
./rclone-sync/configure.sh
./rclone-sync/rclone-sync.sh bootstrap-dry-run
```

Review the dry-run output carefully before establishing the first baseline:

```bash
./rclone-sync/rclone-sync.sh bootstrap
```

After bootstrap, preview and run routine synchronization with `dry-run` and
`sync`. See [rclone synchronization](rclone-sync/README.md) for installation,
recovery, safety, and scheduling details. Existing legacy cloud variables in
`.env` are ignored and may be removed manually after the rclone setup has been
verified.
