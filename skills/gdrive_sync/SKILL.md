---
name: gdrive_sync
description: Synchronize the configured local application storage tree with Google Drive.
---

# Google Drive Sync

This administrative skill synchronizes `LOCAL_STORAGE_PATH` with the Google
Drive root configured by `CLOUD_STORAGE_PATH`. `CLOUD_PROVIDER` must be
`google`.

## Usage

Run an initial pull before the first incremental sync:

```bash
conda run -n sictic-env python -m skills.gdrive_sync pull
```

The complete command surface is:

```bash
conda run -n sictic-env python -m skills.gdrive_sync push
conda run -n sictic-env python -m skills.gdrive_sync pull
conda run -n sictic-env python -m skills.gdrive_sync sync --local-wins
conda run -n sictic-env python -m skills.gdrive_sync sync --cloud-wins --dry-run --json
```

Optional overrides include `--local-root`, `--cloud-root`,
`--credentials-path`, `--token-path`, `--state-dir`, `--log-dir`,
`--exclude`, `--lock-timeout`, and `--verbose`.

File transfers are logged with operation progress, for example
`upload 5/37 path/to/file.md` or `download 6/37 path/to/file.pdf`.

## Operational State

The incremental baseline and Drive changes token are durable operational state,
not disposable cache. They are stored under:

```text
<REPO_PATH>/gdrive_sync_state/<pairing-id>/
```

Logs are written to:

```text
<REPO_PATH>/logs/gdrive-sync.log
```
