#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT"
export PORT="${PORT:-18080}"
PY="${PY:-python3}"
if [ -x /home/ubuntu/miniforge3/envs/sictic-env/bin/python ]; then
  PY=/home/ubuntu/miniforge3/envs/sictic-env/bin/python
fi
"$PY" -m spike.web &
pid=$!
cleanup() { kill "$pid" 2>/dev/null || true; }
trap cleanup EXIT
for _ in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:${PORT}/healthz" >/dev/null; then
    break
  fi
  sleep 0.25
done
curl -fsS "http://127.0.0.1:${PORT}/healthz"
echo
curl -fsS "http://127.0.0.1:${PORT}/api/status" >/dev/null
echo "spike web ok"
