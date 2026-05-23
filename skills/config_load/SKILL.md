# config_load

**Description:**
Compiles Markdown-based configuration files from a Google Drive rclone mount into a single, hierarchical JSON file. It uses caching to ensure it only scans the drive when source `.md` files have been updated.

**Triggers:**
- "Load skill configurations"
- "Refresh the config cache"
- "Compile the Google Drive config"

**Instructions:**
1. Run the Python utility:
   ```bash
   conda run -n sictic-env python -m skills.config_load
   ```
2. The script will output the path to the cached JSON file (e.g., `RESULT_PATH: {{REPO_ROOT}}/cache/config.json`).
3. Use the `read` tool to load the contents of that JSON file if the user requests the specific configuration data, or just confirm to the user that the configuration has been updated.

**Prerequisites:**
- All runtime dependencies (including `rich`) are installed in the project venv at `the Conda environment ` by `{{REPO_ROOT}}/install_skills.sh`.
- The Google Drive must be mounted via rclone to the path set in `REPOSITORY_DIR` (see `.env`).