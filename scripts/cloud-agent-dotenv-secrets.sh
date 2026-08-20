#!/usr/bin/env bash
# Copy Cloud Agent secrets from the process environment into .env.
# lib/env.py loads .env with override=True, so empty template keys wipe
# live secrets unless the injected values are written first.
#
# Source this file; call seed_dotenv_secrets <env_file>.
# Requires env_set KEY VALUE PATH to be defined by the caller.
#
# shellcheck shell=bash

seed_dotenv_secrets() {
  local env_path="${1:-}"
  local key value

  if [ -z "$env_path" ] || [ ! -f "$env_path" ]; then
    return 0
  fi
  if ! declare -F env_set >/dev/null 2>&1; then
    return 0
  fi

  for key in DEALUM_API_KEY DEALUM_DEALROOM_ID \
    LLAMA_CLOUD_API_KEY LLAMA_PARSE_TIER LLAMA_PARSE_VERSION \
    DOCUMENT_PARSER VECTOR_STORE FIREBASE_PROJECT_ID \
    FIRESTORE_EMBEDDING_DIMENSIONS; do  # pragma: allowlist secret
    value="${!key:-}"
    if [ -n "$value" ]; then
      env_set "$key" "$value" "$env_path"
    fi
  done
}
