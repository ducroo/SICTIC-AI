# gdrive-sync

Repo-local Google Drive sync utility for the SICTIC hybrid storage mode.

It reads the existing repo `.env` via `lib.env` and defaults to:

- `STORAGE_MIRROR_PATH` as the local root
- `STORAGE_PATH` as the Google Drive folder ID/root
- `GDRIVE_CREDENTIALS` as the OAuth client credentials path
- `GDRIVE_TOKEN` as the OAuth token path

Install the repo into the active conda environment:

```bash
python -m pip install -e .
```

Then run from any working directory:

```bash
gdrive-sync pull
gdrive-sync push
gdrive-sync sync --conflict-policy local-wins
gdrive-sync sync --conflict-policy cloud-wins --dry-run --json
```

Cron example:

```cron
*/15 * * * * cd /Users/ugubser/Documents/GitHub/SICTIC-AI && /opt/homebrew/anaconda3/bin/conda run -n <env-name> gdrive-sync sync --conflict-policy local-wins
```

Markdown files are written to Drive through the existing `GoogleDriveStorage`
strategy, so local `.md` files become Google Docs and Google Docs are exported
back to local Markdown. Other ordinary files are copied as binary files.

State is stored in the repo-local tool directory:

- `gdrive-sync/.state/`

Streaming pulls persist completed file and folder hashes immediately into a
SQLite checkpoint table. The checkpoint is promoted to the successful baseline
only after the full operation completes without failures.

Logs rotate by default in:

- `gdrive-sync/logs/gdrive-sync.log`
