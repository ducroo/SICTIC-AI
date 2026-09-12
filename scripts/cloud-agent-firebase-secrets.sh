#!/usr/bin/env bash
# Materialize Cloud Agent Firebase/Firestore secrets for ADC.  # pragma: allowlist secret
# FIREBASE_SERVICE_ACCOUNT_JSON must not be written into .env: private_key
# contains `\n` sequences that sed-based env_set corrupts on later boots.
# Write the JSON to a 0600 file and point GOOGLE_APPLICATION_CREDENTIALS at it.
#
# Source this file; call materialize_firebase_secrets [env_file].
# When env_file is given and env_set is defined, path/project vars are written.
# shellcheck shell=bash

materialize_firebase_secrets() {
  local env_path="${1:-}"
  local dest="${FIREBASE_SERVICE_ACCOUNT_FILE:-$HOME/.openclaw/firebase-service-account.json}"
  local sa_json="${FIREBASE_SERVICE_ACCOUNT_JSON:-}"
  local project_id="${FIREBASE_PROJECT_ID:-}"
  local extracted=""
  local wrote=0

  if [ -n "$sa_json" ]; then
    mkdir -p "$(dirname "$dest")"
    extracted="$(
      CONTENT="$sa_json" DEST="$dest" python3 - <<'PY'
import json
import os
from pathlib import Path

raw = os.environ["CONTENT"]
path = Path(os.environ["DEST"])
info = json.loads(raw)
path.write_text(json.dumps(info), encoding="utf-8")
path.chmod(0o600)
print((info.get("project_id") or "").strip())
PY
    )"
    export GOOGLE_APPLICATION_CREDENTIALS="$dest"
    if [ -z "$project_id" ] && [ -n "$extracted" ]; then
      project_id="$extracted"
    fi
    wrote=1
  fi

  if [ -n "$project_id" ]; then
    export FIREBASE_PROJECT_ID="$project_id"
    export GOOGLE_CLOUD_PROJECT="$project_id"
    export GCLOUD_PROJECT="$project_id"
  fi

  if [ -n "$env_path" ] && [ -f "$env_path" ] && declare -F env_set >/dev/null 2>&1; then
    if [ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]; then
      env_set "GOOGLE_APPLICATION_CREDENTIALS" "$GOOGLE_APPLICATION_CREDENTIALS" "$env_path"
    fi
    if [ -n "$project_id" ]; then
      env_set "FIREBASE_PROJECT_ID" "$project_id" "$env_path"
    fi
  fi

  if [ "$wrote" -eq 1 ]; then
    echo "cloud-agent-firebase-secrets: materialized service account for ADC" >&2
  fi
}
