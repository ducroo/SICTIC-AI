#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

if [[ -z "${FIREBASE_PROJECT_ID:-}" ]]; then
  echo "FIREBASE_PROJECT_ID is required." >&2
  exit 1
fi

export SPIKE_URL="${SPIKE_URL:-http://127.0.0.1:8080}"

if ! curl -fsS --max-time 3 "${SPIKE_URL}/healthz" >/dev/null; then
  echo "Spike HTTP is not reachable at ${SPIKE_URL}. Start python -m spike.web first." >&2
  exit 1
fi

if [[ ! -d functions/node_modules ]]; then
  (cd functions && npm install)
fi

# Hosting + Functions only. Do not pass a database emulator; the Python
# process keeps using the production vector store.
exec npx -y firebase-tools@latest emulators:start \
  --only hosting,functions \
  --project "${FIREBASE_PROJECT_ID}"
