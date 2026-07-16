# gdrive-sync

Repo-local Google Drive sync utility for the SICTIC hybrid storage mode.

It reads the existing repo `.env` via `lib.env` and defaults to:

- `LOCAL_STORAGE_PATH` as the local root
- `CLOUD_STORAGE_PATH` as the Google Drive folder ID/root
- `GDRIVE_CREDENTIALS` as the OAuth client credentials path
- `GDRIVE_TOKEN` as the OAuth token path

Run `install.sh` to register both the repository root and `gdrive-sync/` in the
active Conda environment. Then run from any working directory:

```bash
python -m gdrive_sync pull
python -m gdrive_sync push
python -m gdrive_sync sync --conflict-policy local-wins
python -m gdrive_sync sync --conflict-policy cloud-wins --dry-run --json
```

Cron example:

```cron
*/15 * * * * cd /Users/ugubser/Documents/GitHub/SICTIC-AI && /opt/homebrew/anaconda3/bin/conda run -n <env-name> python -m gdrive_sync sync --conflict-policy local-wins
```

Markdown files are written to Drive through the existing `GoogleDriveStorage`
strategy, so local `.md` files become Google Docs and Google Docs are exported
back to local Markdown. Other ordinary files are copied as binary files.

State is stored in the repo-local durable state directory:

- `gdrive_sync_state/<pairing-id>/`

Streaming pulls persist completed file and folder hashes immediately into a
SQLite checkpoint table. The checkpoint is promoted to the successful baseline
only after the full operation completes without failures.

Pull behavior:

- If no successful baseline and Drive start page token exist yet, `pull` performs
  a full recursive bootstrap walk.
- After a successful bootstrap, later `pull` runs use the Drive Changes API
  (`changes.list`) from the stored page token and apply only changed, created,
  moved, renamed, or deleted Drive entries.
- If Drive reports that the stored change token expired, `pull` falls back to a
  full recursive walk and writes a fresh baseline/token.

Sync behavior:

- If a successful baseline and Drive start page token exist, `sync` uses
  `changes.list` for cloud-side changes and local-vs-baseline hashes for
  local-side changes.
- `sync --conflict-policy local-wins` uploads local-only changes to Drive and
  applies cloud-only changes locally. If both sides changed the same path, the
  local version becomes canonical.
- `sync --conflict-policy cloud-wins` is non-destructive: cloud adds and
  updates are applied locally, but nothing is deleted on either side. Local-only
  changes are not uploaded.
- If no baseline/token exists, `sync` fails and asks you to run `pull` first.

Logs rotate by default in:

- `logs/gdrive-sync.log`
