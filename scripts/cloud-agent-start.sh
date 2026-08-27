#!/usr/bin/env bash
# Per-boot Cloud Agent start: materialize Dealum secrets and bring up Qdrant.
# Docling is an in-process library. Skips Ollama; embeddings/LLM use API keys.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if ! command -v conda >/dev/null 2>&1 && [ -x "$HOME/miniforge3/bin/conda" ]; then
  # shellcheck disable=SC1091
  eval "$("$HOME/miniforge3/bin/conda" shell.bash hook)"
fi

# shellcheck disable=SC1091
source "$REPO_ROOT/scripts/cloud-agent-dotenv-secrets.sh"
if [ -f "$REPO_ROOT/.env" ]; then
  seed_dotenv_secrets "$REPO_ROOT/.env"
fi

./launch.sh start qdrant

# Wait until Qdrant answers.
host="${QDRANT_HOST:-http://localhost:6333}"
for _ in $(seq 1 60); do
  if curl -fsS "$host/readyz" >/dev/null 2>&1 || curl -fsS "$host/" >/dev/null 2>&1; then
    echo "cloud-agent-start: qdrant ready at $host"
    exit 0
  fi
  sleep 1
done

echo "cloud-agent-start: qdrant did not become ready at $host" >&2
exit 1
