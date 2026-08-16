#!/usr/bin/env bash
# Materialize Cloud Agent GDrive JSON secrets into credential files.
# Runtime (gdrive_sync / GoogleDriveStorage) expects file paths in
# GDRIVE_CREDENTIALS and GDRIVE_TOKEN. Secrets UI can hold JSON in
# GDRIVE_CREDENTIALS_JSON / GDRIVE_TOKEN_JSON (preferred) or, for
# backwards compatibility, JSON blobs in GDRIVE_CREDENTIALS / GDRIVE_TOKEN.
#
# Source this file; call materialize_gdrive_secrets [env_file].
# When env_file is given, path vars are written there. Process env is
# always updated so the current boot sees the paths.
#
# shellcheck shell=bash

# Write JSON content to dest (mode 0600). If content is already an existing
# file path, print that path. Prints the path used on stdout.
# Returns 1 when content is empty or neither JSON nor an existing file.
materialize_json_secret() {
  local content="$1"
  local dest="$2"
  local trimmed

  if [ -z "${content}" ]; then
    return 1
  fi

  # Trim leading whitespace for the JSON-vs-path check only.
  trimmed="${content#"${content%%[![:space:]]*}"}"
  case "$trimmed" in
    \{*)
      mkdir -p "$(dirname "$dest")"
      CONTENT="$content" DEST="$dest" python3 - <<'PY'
import json
import os
from pathlib import Path

raw = os.environ["CONTENT"]
path = Path(os.environ["DEST"])
try:
    json.loads(raw)
except json.JSONDecodeError as exc:
    raise SystemExit(f"invalid JSON for {path}: {exc}") from exc
path.write_text(raw, encoding="utf-8")
path.chmod(0o600)
print(path)
PY
      ;;
    *)
      if [ -f "$content" ]; then
        printf '%s\n' "$content"
        return 0
      fi
      if [ -f "${content/#\~/$HOME}" ]; then
        printf '%s\n' "${content/#\~/$HOME}"
        return 0
      fi
      return 1
      ;;
  esac
}

# Prefer *_JSON secrets; fall back to GDRIVE_* (path or legacy JSON blob).
materialize_gdrive_secrets() {
  local env_path="${1:-}"
  local creds_dest="${GDRIVE_CREDENTIALS_FILE:-$HOME/.openclaw/gdrive-ops-credentials.json}"
  local token_dest="${GDRIVE_TOKEN_FILE:-$HOME/.openclaw/gdrive-ops-token.json}"
  local materialized
  local wrote=0

  if materialized=$(materialize_json_secret \
      "${GDRIVE_CREDENTIALS_JSON:-${GDRIVE_CREDENTIALS:-}}" "$creds_dest"); then
    export GDRIVE_CREDENTIALS="$materialized"
    if [ -n "$env_path" ] && [ -f "$env_path" ] && declare -F env_set >/dev/null 2>&1; then
      env_set "GDRIVE_CREDENTIALS" "$materialized" "$env_path"
    fi
    wrote=1
  fi

  if materialized=$(materialize_json_secret \
      "${GDRIVE_TOKEN_JSON:-${GDRIVE_TOKEN:-}}" "$token_dest"); then
    export GDRIVE_TOKEN="$materialized"
    if [ -n "$env_path" ] && [ -f "$env_path" ] && declare -F env_set >/dev/null 2>&1; then
      env_set "GDRIVE_TOKEN" "$materialized" "$env_path"
    fi
    wrote=1
  fi

  if [ "$wrote" -eq 1 ]; then
    echo "cloud-agent-gdrive-secrets: materialized GDrive credential files" >&2
  fi
}
