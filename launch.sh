#!/bin/bash
# launch.sh

PID_DIR="./.pids"
LOG_DIR="./logs"
mkdir -p "$PID_DIR" "$LOG_DIR"

SERVICES=(qdrant ollama)

load_env_file() {
    if [ ! -f .env ]; then
        return
    fi
    while IFS= read -r line; do
        case "$line" in
            ""|\#*) continue ;;
            *=*)
                key="${line%%=*}"
                val="${line#*=}"
                key="$(printf '%s' "$key" | xargs)"
                val="$(printf '%s' "$val" | xargs)"
                case "$val" in
                    \"*\") val="${val#\"}"; val="${val%\"}" ;;
                    \'*\') val="${val#\'}"; val="${val%\'}" ;;
                esac
                if [ -z "$(eval "printf '%s' \"\${$key:-}\"")" ]; then
                    export "$key=$val"
                fi
                ;;
        esac
    done < .env
}

ollama_model_name() {
    local raw="$1"
    case "$raw" in
        ollama/*) printf '%s\n' "${raw#ollama/}" ;;
        *) printf '\n' ;;
    esac
}

ollama_has_model() {
    local model="$1"
    local host="${2:-${OLLAMA_HOST:-http://localhost:11434}}"
    if curl -fsS "$host/api/tags" 2>/dev/null | grep -Eq "\"(name|model)\":\"$model\""; then
        return 0
    fi
    if command -v ollama >/dev/null 2>&1; then
        ollama list 2>/dev/null | awk 'NR > 1 {print $1}' | grep -qx "$model"
        return $?
    fi
    return 1
}

ensure_ollama_model() {
    local configured="$1"
    local label="$2"
    local host="${3:-${OLLAMA_HOST:-http://localhost:11434}}"
    local model
    model="$(ollama_model_name "$configured")"
    if [ -z "$model" ]; then
        return
    fi
    if ! curl -s "$host" >/dev/null 2>&1; then
        echo "WARNING: ollama endpoint for $label is not responding at $host; cannot check/pull $model."
        return
    fi
    if ollama_has_model "$model" "$host"; then
        echo "ollama model present ($label): $model"
        return
    fi
    echo "Pulling missing ollama model ($label): $model"
    if curl -fsS "$host/api/pull" \
        -H "Content-Type: application/json" \
        -d "{\"name\":\"$model\",\"stream\":false}" >/dev/null; then
        echo "ollama model ready ($label): $model"
        return
    fi
    if command -v ollama >/dev/null 2>&1; then
        ollama pull "$model"
        return
    fi
    echo "ERROR: Failed to pull ollama model '$model' via $host/api/pull, and ollama CLI is not on PATH." >&2
    return 1
}

ensure_ollama_models() {
    local ollama_host="${OLLAMA_HOST:-http://localhost:11434}"
    local llm_host="${LLM_BASE_URL:-$ollama_host}"
    local embedding_host="${EMBEDDING_BASE_URL:-$ollama_host}"
    local llm_model="${LLM_MODEL:-${DEFAULT_LLM:-}}"
    local embedding_model="${EMBEDDING_MODEL:-${DEFAULT_EMBEDDINGS:-}}"

    ensure_ollama_model "$llm_model" "LLM_MODEL" "$llm_host"
    ensure_ollama_model "${DEFAULT_VLM:-}" "DEFAULT_VLM" "$ollama_host"
    ensure_ollama_model "$embedding_model" "EMBEDDING_MODEL" "$embedding_host"
}

# ---------- start ----------
start_qdrant() {
    if [ -f "$PID_DIR/qdrant.pid" ] && ps -p "$(cat "$PID_DIR/qdrant.pid")" > /dev/null 2>&1; then
        echo "qdrant already running (pid $(cat "$PID_DIR/qdrant.pid"))"
        return
    fi

    QDRANT_DIR="./qdrant"
    QDRANT_BIN="$QDRANT_DIR/qdrant"

    if [ ! -x "$QDRANT_BIN" ]; then
        echo "qdrant binary not found. Attempting to download..."
        mkdir -p "$QDRANT_DIR"
        
        OS=$(uname -s)
        ARCH=$(uname -m)
        
        if [ "$OS" = "Darwin" ]; then
            if [ "$ARCH" = "arm64" ]; then
                URL="https://github.com/qdrant/qdrant/releases/latest/download/qdrant-aarch64-apple-darwin.tar.gz"
            else
                URL="https://github.com/qdrant/qdrant/releases/latest/download/qdrant-x86_64-apple-darwin.tar.gz"
            fi
        elif [ "$OS" = "Linux" ]; then
            if [ "$ARCH" = "aarch64" ]; then
                URL="https://github.com/qdrant/qdrant/releases/latest/download/qdrant-aarch64-unknown-linux-gnu.tar.gz"
            else
                URL="https://github.com/qdrant/qdrant/releases/latest/download/qdrant-x86_64-unknown-linux-gnu.tar.gz"
            fi
        else
            echo "ERROR: Unsupported OS for auto-download: $OS"
            return 1
        fi
        
        echo "Downloading Qdrant from $URL ..."
        curl -L "$URL" | tar -xz -C "$QDRANT_DIR"
        if [ ! -x "$QDRANT_BIN" ]; then
            echo "ERROR: Failed to download or extract Qdrant."
            return 1
        fi
    fi

    echo "Starting qdrant..."
    mkdir -p qdrant_data
    QDRANT__STORAGE__STORAGE_PATH="./qdrant_data" \
        "$QDRANT_BIN" > "$LOG_DIR/qdrant.log" 2>&1 &
    echo $! > "$PID_DIR/qdrant.pid"
}

start_ollama() {
    load_env_file

    if curl -s "${OLLAMA_HOST:-http://localhost:11434}" > /dev/null 2>&1; then
        echo "ollama is already responding on ${OLLAMA_HOST:-http://localhost:11434} (system service or already running externally)"
        ensure_ollama_models
        return
    fi

    if ! command -v ollama >/dev/null 2>&1; then
        echo "WARNING: ollama is not installed or not in PATH. Skipping ollama start."
        return
    fi

    if [ -f "$PID_DIR/ollama.pid" ] && ps -p "$(cat "$PID_DIR/ollama.pid")" > /dev/null 2>&1; then
        echo "ollama already running (pid $(cat "$PID_DIR/ollama.pid"))"
        return
    fi

    echo "Starting ollama..."
    ollama serve > "$LOG_DIR/ollama.log" 2>&1 &
    echo $! > "$PID_DIR/ollama.pid"

    for _ in $(seq 1 30); do
        if curl -s "${OLLAMA_HOST:-http://localhost:11434}" > /dev/null 2>&1; then
            ensure_ollama_models
            return
        fi
        sleep 1
    done
    echo "WARNING: ollama did not respond after startup; model provisioning skipped."
}

# ---------- stop ----------
stop_pidfile() {
    local name="$1"
    local pidfile="$PID_DIR/$name.pid"
    if [ -f "$pidfile" ]; then
        local pid
        pid=$(cat "$pidfile")
        if ps -p "$pid" > /dev/null 2>&1; then
            echo "Stopping $name (pid $pid)..."
            kill "$pid"
        else
            echo "$name not running (stale pidfile)"
        fi
        rm -f "$pidfile"
    else
        echo "$name not running"
    fi
}

stop_qdrant()  { stop_pidfile qdrant; }
stop_ollama()  { stop_pidfile ollama; }

# ---------- status ----------
status_pidfile() {
    local name="$1"
    local pidfile="$PID_DIR/$name.pid"
    if [ -f "$pidfile" ] && ps -p "$(cat "$pidfile")" > /dev/null 2>&1; then
        echo "$name is running (pid $(cat "$pidfile"))"
    else
        echo "$name is NOT running"
    fi
}

status_qdrant()  { status_pidfile qdrant; }
status_ollama()  {
    if curl -s http://localhost:11434 > /dev/null 2>&1; then
        echo "ollama is running (responding on port 11434)"
    else
        status_pidfile ollama
    fi
}

# ---------- dispatch ----------
is_valid_service() {
    local s="$1"
    for svc in "${SERVICES[@]}"; do
        [ "$svc" = "$s" ] && return 0
    done
    return 1
}

run_action() {
    local action="$1"
    local target="${2:-all}"

    if [ "$target" = "all" ]; then
        for svc in "${SERVICES[@]}"; do
            "${action}_${svc}"
        done
        return
    fi

    if ! is_valid_service "$target"; then
        echo "Unknown service: $target"
        echo "Available services: ${SERVICES[*]} all"
        exit 1
    fi

    "${action}_${target}"
}

usage() {
    echo "Usage: $0 {start|stop|status} [service|all]"
    echo "Services: ${SERVICES[*]}"
    echo "If service is omitted, 'all' is assumed."
}

case "$1" in
    start|stop|status) run_action "$1" "$2" ;;
    ""|-h|--help|help) usage ;;
    *) usage; exit 1 ;;
esac
