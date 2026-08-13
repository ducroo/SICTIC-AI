#!/usr/bin/env bash
# Per-boot Cloud Agent start: bring up Qdrant (Docling is an in-process library).
# Skips Ollama; embeddings/LLM use OpenRouter/OpenAI via API keys.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if ! command -v conda >/dev/null 2>&1 && [ -x "$HOME/miniforge3/bin/conda" ]; then
  # shellcheck disable=SC1091
  eval "$("$HOME/miniforge3/bin/conda" shell.bash hook)"
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
