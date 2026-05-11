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
   /home/node/miniconda3/bin/conda run -n claw-env python /home/node/.openclaw/workspace-sictic-ai/skills/config_load/Config_Load.py
   ```
2. The script will output the path to the cached JSON file (e.g., `RESULT_PATH: /home/node/.openclaw/workspace-sictic-ai/cache/config.json`).
3. Use the `read` tool to load the contents of that JSON file if the user requests the specific configuration data, or just confirm to the user that the configuration has been updated.

**Prerequisites:**
- The `rich` python library should be installed in the `claw-env` conda environment (`conda install rich` or `pip install rich`).
- The Google Drive must be mounted via rclone to `workspace-sictic-ai/gdrive/`.