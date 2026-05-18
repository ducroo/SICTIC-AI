#!/bin/bash
# /Users/openclaw/.openclaw/workspace-ops/SICTIC-AI/macos_launch.sh

PID_DIR="./.pids"
LOG_DIR="./logs"
mkdir -p "$PID_DIR" "$LOG_DIR"

SERVICES=(qdrant ollama rclone)

# Pull GDRIVE_MOUNT out of .env so rclone knows where to mount.
# Targeted extraction (not `source .env`) because the file has python-dotenv-style
# entries with spaces around `=` that aren't valid shell.
if [ -z "${GDRIVE_MOUNT:-}" ] && [ -f .env ]; then
    GDRIVE_MOUNT=$(awk -F= '/^[[:space:]]*GDRIVE_MOUNT[[:space:]]*=/ { sub(/^[^=]*=[[:space:]]*/, ""); gsub(/^"|"$/, ""); print; exit }' .env)
    export GDRIVE_MOUNT
fi

# ---------- start ----------
start_qdrant() {
    if [ -f "$PID_DIR/qdrant.pid" ] && ps -p "$(cat "$PID_DIR/qdrant.pid")" > /dev/null 2>&1; then
        echo "qdrant already running (pid $(cat "$PID_DIR/qdrant.pid"))"
        return
    fi
    if [ ! -x ./qdrant/qdrant ]; then
        echo "ERROR: ./qdrant/qdrant not found. Download from https://github.com/qdrant/qdrant/releases (qdrant-aarch64-apple-darwin.tar.gz)"
        return 1
    fi
    echo "Starting qdrant..."
    mkdir -p qdrant_data
    QDRANT__STORAGE__STORAGE_PATH="./qdrant_data" \
        ./qdrant/qdrant > "$LOG_DIR/qdrant.log" 2>&1 &
    echo $! > "$PID_DIR/qdrant.pid"
}

start_ollama() {
    if [ -f "$PID_DIR/ollama.pid" ] && ps -p "$(cat "$PID_DIR/ollama.pid")" > /dev/null 2>&1; then
        echo "ollama already running (pid $(cat "$PID_DIR/ollama.pid"))"
        return
    fi

    # Export every OLLAMA_* key from .env into our env so `ollama serve` reads
    # them at startup (NUM_PARALLEL, KV_CACHE_TYPE, FLASH_ATTENTION, HOST, …).
    # Skill code reads .env separately via lib/env.py; this block is only for
    # the daemon. Existing shell env wins over .env values.
    if [ -f .env ]; then
        while IFS= read -r line; do
            case "$line" in
                OLLAMA_*=*)
                    key="${line%%=*}"
                    val="${line#*=}"
                    # strip optional surrounding double-quotes
                    case "$val" in
                        \"*\") val="${val#\"}"; val="${val%\"}" ;;
                    esac
                    # don't override if already set in the shell environment
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

start_rclone() {
    if [ -f "$PID_DIR/rclone.pid" ] && ps -p "$(cat "$PID_DIR/rclone.pid")" > /dev/null 2>&1; then
        echo "rclone already running (pid $(cat "$PID_DIR/rclone.pid"))"
        return
    fi
    if [ -z "${GDRIVE_MOUNT:-}" ]; then
        echo "ERROR: GDRIVE_MOUNT is not set (check .env)"
        return 1
    fi
    mkdir -p "$GDRIVE_MOUNT"
    echo "Starting rclone (mount=$GDRIVE_MOUNT, rc=5572)..."
    rclone mount gdrive: "$GDRIVE_MOUNT" \
        --vfs-cache-mode full \
        --rc --rc-addr 0.0.0.0:5572 --rc-no-auth \
        > "$LOG_DIR/rclone.log" 2>&1 &
    echo $! > "$PID_DIR/rclone.pid"
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
stop_rclone()  { stop_pidfile rclone; }

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
status_ollama()  { status_pidfile ollama; }
status_rclone()  { status_pidfile rclone; }

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
