# Google Drive synchronization with rclone

This optional helper synchronizes the local SICTIC-AI application-storage tree
with a folder in Google Drive. Skills remain local-only: they do not access
Google Drive or invoke synchronization themselves.

Markdown files are imported as native Google Docs. Native Google Docs are
exported locally as Markdown. Other files are transferred without conversion.
Because these conversion flags are specific to Google Drive, the helper rejects
other rclone backend types.

## 1. Install and authenticate rclone

On macOS with Homebrew:

```bash
brew install rclone
```

On Linux or WSL2, use rclone's official installer after reviewing it:

```bash
sudo -v
curl https://rclone.org/install.sh | sudo bash
```

Create and authenticate a Google Drive remote. This connection belongs to you;
the SICTIC-AI installer does not create, store, or manage its credentials.

```bash
rclone config
```

## 2. Configure the synchronization pair

Create the destination folder in Google Drive, then run:

```bash
./rclone-sync/configure.sh
```

The setup validates that the selected rclone remote uses the Google Drive
backend and that both roots exist. It writes machine-specific values to
`rclone-sync/config.env`, which is excluded from Git. For scripted setup, pass
both roots explicitly:

```bash
./rclone-sync/configure.sh \
  --local-root /absolute/path/to/local_storage/storage \
  --remote gdrive:SICTIC-AI
```

If you use a non-default rclone configuration file, set
`RCLONE_CONFIG_FILE=/absolute/path/to/rclone.conf` while running
`configure.sh`; the path is retained in `config.env`.

## 3. Establish the first baseline

The initial bootstrap treats the local tree as authoritative when the same file
differs on both sides. Files that exist on only one side are copied to the other
side. Review the complete dry-run before allowing changes:

```bash
./rclone-sync/rclone-sync.sh bootstrap-dry-run
./rclone-sync/rclone-sync.sh bootstrap
```

Use `bootstrap` only for first initialization or after a diagnosed state change
that requires a new bisync baseline.

## Routine commands

```bash
./rclone-sync/rclone-sync.sh dry-run
./rclone-sync/rclone-sync.sh sync
```

Run `dry-run` whenever you are uncertain about pending operations. The helper
uses a safety marker at both roots, a local non-overlap lock, a maximum of ten
deletions per run, and retained conflict copies. It also enables rclone's
resilient and interruption-recovery modes.

## Recovery

`recover-from-drive` rebuilds the baseline with Google Drive authoritative for
files that differ on both sides:

```bash
./rclone-sync/rclone-sync.sh recover-from-drive
```

This can overwrite local versions. Use it only after diagnosing the failure and
confirming that Drive contains the intended canonical files.

## State and logs

- `rclone-sync/config.env`: private machine-specific roots; never commit it.
- `rclone-sync/state/`: durable bisync listings; do not delete as cache.
- `rclone-sync/logs/`: immutable log for each invocation.
- `logs/rclone.log`: continuous operational log.

Changing `filters.txt` requires a new reviewed bootstrap because rclone protects
against applying changed filters to an existing baseline. Directory modification
times are not written locally; file contents and file modification times remain
synchronized.

Local Markdown renames recreate the corresponding native Google Doc and lose
its Drive revision identity. Rename native Google Docs in Drive when retaining
that identity matters.
