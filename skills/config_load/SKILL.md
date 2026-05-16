# config_load

**Description:**
Compiles Markdown-based configuration files from Google Drive (via `skills.utils.storage`) into a single, hierarchical JSON file. It uses caching to ensure it only scans the drive when source `.md` files have been updated.

**Triggers:**
- "Load skill configurations"
- "Refresh the config cache"
- "Compile the Google Drive config"

**Instructions:**
1. Run the Python utility:
   ```bash
   python -m skills.config_load
   ```
2. The script will output the path to the cached JSON file (e.g., `RESULT_PATH: $CONFIG_CACHE_DIR/config.json`).
3. Use the `read` tool to load the contents of that JSON file if the user requests the specific configuration data, or just confirm to the user that the configuration has been updated.

**Prerequisites:**
- Drive access is configured (either rclone FUSE mount via `GDRIVE_MOUNT`, or native Drive API via `GDRIVE_USE_API=1` — see top-level README).