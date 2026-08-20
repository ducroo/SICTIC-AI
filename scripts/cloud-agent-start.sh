#!/usr/bin/env bash
# Per-boot Cloud Agent start: materialize GDrive/Firebase/Dealum secrets, bring
# up Qdrant unless VECTOR_STORE=firestore. Docling / LlamaParse are in-process.  # pragma: allowlist secret
# Skips Ollama; embeddings/LLM use API keys.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if ! command -v conda >/dev/null 2>&1 && [ -x "$HOME/miniforge3/bin/conda" ]; then
  # shellcheck disable=SC1091
  eval "$("$HOME/miniforge3/bin/conda" shell.bash hook)"
fi

# Builds skip install on later boots; secrets are injected per pod, so refresh
# GDrive credential files, Dealum keys, and .env path pointers on every start.
env_set() {
  local key="$1"
  local value="$2"
  local path="$3"
  local tmp escaped
  tmp="${path}.tmp.$$"
  escaped=$(printf '%s' "$value" | sed 's/[\/&]/\\&/g')
  if [ -f "$path" ] && grep -q "^[[:space:]]*$key[[:space:]]*=" "$path"; then
    sed "s/^\\([[:space:]]*$key[[:space:]]*=\\).*/\\1$escaped/" "$path" > "$tmp"
  else
    if [ -f "$path" ]; then
      cp "$path" "$tmp"
    else
      : > "$tmp"
    fi
    printf '%s=%s\n' "$key" "$value" >> "$tmp"
  fi
  mv "$tmp" "$path"
}

# shellcheck disable=SC1091
source "$REPO_ROOT/scripts/cloud-agent-gdrive-secrets.sh"
# shellcheck disable=SC1091
source "$REPO_ROOT/scripts/cloud-agent-dotenv-secrets.sh"
# shellcheck disable=SC1091
source "$REPO_ROOT/scripts/cloud-agent-firebase-secrets.sh"

# Prefer SaaS spike backends when secrets are present on this pod.
# Explicit process-env DOCUMENT_PARSER=docling / VECTOR_STORE=qdrant still wins.
if [ -f "$REPO_ROOT/.env" ]; then
  if [ -n "${LLAMA_CLOUD_API_KEY:-}" ] && [ "${DOCUMENT_PARSER:-}" != "docling" ]; then
    env_set "DOCUMENT_PARSER" "llamaparse" "$REPO_ROOT/.env"  # pragma: allowlist secret
  fi
  if { [ -n "${FIREBASE_SERVICE_ACCOUNT_JSON:-}" ] || [ -n "${FIREBASE_PROJECT_ID:-}" ]; } \
    && [ "${VECTOR_STORE:-}" != "qdrant" ]; then
    env_set "VECTOR_STORE" "firestore" "$REPO_ROOT/.env"  # pragma: allowlist secret
    if [ -z "${FIRESTORE_EMBEDDING_DIMENSIONS:-}" ]; then  # pragma: allowlist secret
      env_set "FIRESTORE_EMBEDDING_DIMENSIONS" "1536" "$REPO_ROOT/.env"  # pragma: allowlist secret
    fi
  fi
  materialize_gdrive_secrets "$REPO_ROOT/.env"
  seed_dotenv_secrets "$REPO_ROOT/.env"
  materialize_firebase_secrets "$REPO_ROOT/.env"
else
  materialize_gdrive_secrets
  materialize_firebase_secrets
fi

# After secrets are written, re-read VECTOR_STORE (process env wins over .env).
vector_store="${VECTOR_STORE:-}"
if [ -z "$vector_store" ] && [ -f "$REPO_ROOT/.env" ]; then
  vector_store="$(
    grep -E '^[[:space:]]*VECTOR_STORE[[:space:]]*=' "$REPO_ROOT/.env" 2>/dev/null \
      | tail -n 1 \
      | cut -d= -f2- \
      | tr -d '"' \
      | tr -d "'" \
      | tr -d '[:space:]' \
      || true
  )"
fi
vector_store="${vector_store:-qdrant}"

if [ "$vector_store" = "firestore" ]; then  # pragma: allowlist secret
  echo "cloud-agent-start: VECTOR_STORE=firestore; skipping local Qdrant"  # pragma: allowlist secret
  exit 0
fi

./launch.sh start qdrant

# Wait until Qdrant answers.
host="${QDRANT_HOST:-http://127.0.0.1:6333}"
for _ in $(seq 1 60); do
  if curl -fsS "$host/readyz" >/dev/null 2>&1 || curl -fsS "$host/" >/dev/null 2>&1; then
    echo "cloud-agent-start: qdrant ready at $host"
    exit 0
  fi
  sleep 1
done

echo "cloud-agent-start: qdrant did not become ready at $host" >&2
exit 1
