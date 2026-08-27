---
name: config_load
description: Compile repository Markdown configuration files into a cached hierarchical JSON file. Use when configuration prompts, skill settings, or the config cache need to be loaded, refreshed, or inspected.
---

# config_load

**Description:**
Compiles Markdown-based configuration files from the repository's local
`config/` tree into a single hierarchical JSON file. It uses caching to avoid
recompiling unchanged source files.

**Triggers:**
- "Load skill configurations"
- "Refresh the config cache"
- "Compile the local config"

**Instructions:**
1. Run the harness command:
   ```bash
   conda run -n sictic-env python -m skills.harness /config
   ```
2. The script will output the path to the cached JSON file (e.g., `RESULT_PATH: {{LOCAL_DATA_PATH}}/cache/config.json`).
3. Use the `read` tool to load the contents of that JSON file if the user requests the specific configuration data, or just confirm to the user that the configuration has been updated.

**Prerequisites:**
- All runtime dependencies (including `rich`) are installed in the `sictic-env` Conda environment by `{{REPO_ROOT}}/install.sh`.
- `REPO_PATH` must point to the repository containing the `config/` tree.
