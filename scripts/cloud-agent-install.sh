#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for SICTIC-AI.
# Creates/updates the conda env (Docling + deps), installs skills non-interactively,
# and seeds .env with OpenAI (LLM/VLM) + OpenRouter (embeddings) defaults.
# Secrets come from the Cloud Agent environment; do not commit .env.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

ensure_conda() {
  if command -v conda >/dev/null 2>&1; then
    return
  fi
  if [ -x "$HOME/miniforge3/bin/conda" ]; then
    # shellcheck disable=SC1091
    eval "$("$HOME/miniforge3/bin/conda" shell.bash hook)"
    return
  fi
  echo "cloud-agent-install: conda not found; installing Miniforge..." >&2
  curl -fsSL -o /tmp/Miniforge3.sh \
    "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"
  bash /tmp/Miniforge3.sh -b -p "$HOME/miniforge3"
  # shellcheck disable=SC1091
  eval "$("$HOME/miniforge3/bin/conda" shell.bash hook)"
}

env_set() {
  local key="$1"
  local value="$2"
  local path="$3"
  local tmp escaped
  tmp="${path}.tmp.$$"
  escaped=$(printf '%s' "$value" | sed 's/[\/&]/\\&/g')
  if grep -q "^[[:space:]]*$key[[:space:]]*=" "$path"; then
    sed "s/^\\([[:space:]]*$key[[:space:]]*=\\).*/\\1$escaped/" "$path" > "$tmp"
  else
    cp "$path" "$tmp"
    printf '%s=%s\n' "$key" "$value" >> "$tmp"
  fi
  mv "$tmp" "$path"
}

seed_cloud_env() {
  local env_path="$REPO_ROOT/.env"
  local template="$REPO_ROOT/.env-template"
  local skills_target="${INSTALLED_SKILLS_PATH:-$REPO_ROOT/.openclaw-skills}"

  if [ ! -f "$env_path" ]; then
    cp "$template" "$env_path"
  fi

  # Paths
  env_set "REPO_PATH" "$REPO_ROOT" "$env_path"
  env_set "INSTALLED_SKILLS_PATH" "$skills_target" "$env_path"
  env_set "LOCAL_STORAGE_PATH" "${LOCAL_STORAGE_PATH:-$REPO_ROOT/.storage}" "$env_path"
  env_set "LOCAL_DATA_PATH" "${LOCAL_DATA_PATH:-$REPO_ROOT}" "$env_path"
  env_set "QDRANT_HOST" "${QDRANT_HOST:-http://localhost:6333}" "$env_path"

  # Prefer OpenAI for text/vision; OpenRouter for embeddings (no local Ollama).
  env_set "LLM_MODEL" "${LLM_MODEL:-openai/gpt-4o-mini}" "$env_path"
  env_set "LLM_BASE_URL" "${LLM_BASE_URL:-}" "$env_path"
  env_set "VLM_MODEL" "${VLM_MODEL:-openai/gpt-4o-mini}" "$env_path"
  env_set "VLM_BASE_URL" "${VLM_BASE_URL:-}" "$env_path"
  env_set "EMBEDDING_MODEL" "${EMBEDDING_MODEL:-openrouter/openai/text-embedding-3-small}" "$env_path"
  env_set "EMBEDDING_BASE_URL" "${EMBEDDING_BASE_URL:-}" "$env_path"
  env_set "RANKED_LLMS" "${RANKED_LLMS:-openai/gpt-4o-mini}" "$env_path"
  env_set "CLOUD_PROVIDER" "${CLOUD_PROVIDER:-}" "$env_path"

  # Map Cloud Agent secrets into .env when present (never print values).
  if [ -n "${LLM_API_KEY:-}" ]; then
    env_set "LLM_API_KEY" "$LLM_API_KEY" "$env_path"
  elif [ -n "${OPENAI_API_KEY:-}" ]; then
    env_set "LLM_API_KEY" "$OPENAI_API_KEY" "$env_path"
  fi
  if [ -n "${VLM_API_KEY:-}" ]; then
    env_set "VLM_API_KEY" "$VLM_API_KEY" "$env_path"
  elif [ -n "${LLM_API_KEY:-}" ]; then
    env_set "VLM_API_KEY" "$LLM_API_KEY" "$env_path"
  elif [ -n "${OPENAI_API_KEY:-}" ]; then
    env_set "VLM_API_KEY" "$OPENAI_API_KEY" "$env_path"
  fi
  if [ -n "${EMBEDDING_API_KEY:-}" ]; then
    env_set "EMBEDDING_API_KEY" "$EMBEDDING_API_KEY" "$env_path"
  elif [ -n "${OPENROUTER_API_KEY:-}" ]; then
    env_set "EMBEDDING_API_KEY" "$OPENROUTER_API_KEY" "$env_path"
  fi
}

ensure_conda
seed_cloud_env

SKILLS_TARGET="${INSTALLED_SKILLS_PATH:-$REPO_ROOT/.openclaw-skills}"
mkdir -p "$SKILLS_TARGET"

# install.sh is interactive by default; Cloud Agents must use --non-interactive.
./install.sh --non-interactive --target "$SKILLS_TARGET"

# Prefetch the Qdrant binary so start is fast after snapshot (do not leave a
# process running from install — Cloud Agent start owns the daemon).
if [ ! -x "$REPO_ROOT/qdrant/qdrant" ]; then
  ./launch.sh start qdrant
  ./launch.sh stop qdrant || true
fi

echo "cloud-agent-install: done (conda env + Docling + skills + Qdrant binary)"
