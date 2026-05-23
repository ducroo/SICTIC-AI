#!/bin/bash
# launch.sh

PID_DIR="./.pids"
LOG_DIR="./logs"
mkdir -p "$PID_DIR" "$LOG_DIR"

SERVICES=(qdrant ollama)

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
    if curl -s http://localhost:11434 > /dev/null 2>&1; then
        echo "ollama is already responding on localhost:11434 (system service or already running externally)"
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

    if [ -f .env ]; then
        while IFS= read -r line; do
            case "$line" in
                OLLAMA_*=*)
                    key="${line%%=*}"
                    val="${line#*=}"
                    case "$val" in
                        \"*\") val="${val#\"}"; val="${val%\"}" ;;
                    esac
                    if [ -z "$(eval "printf '%s' \"\${$key:-}\"")" ]; then
                        export "$key=$val"
                        echo "  ollama env: $key=$val"
                    fi
                    ;;
            esac
        done < .env
    fi

    echo "Starting ollama..."
    ollama serve > "$LOG_DIR/ollama.log" 2>&1 &
    echo $! > "$PID_DIR/ollama.pid"
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