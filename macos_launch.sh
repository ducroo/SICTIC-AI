#!/bin/bash
# /Users/openclaw/.openclaw/workspace-ops/SICTIC-AI/macos_launch.sh

PID_DIR="./.pids"
LOG_DIR="./logs"
COMPOSE_FILE="docker-compose.macos.yml"
mkdir -p "$PID_DIR" "$LOG_DIR"

SERVICES=(qdrant docling llama rclone)

# ---------- start ----------
start_qdrant() {
    echo "Starting qdrant..."
    podman compose -f "$COMPOSE_FILE" up -d qdrant
}

start_docling() {
    if [ -f "$PID_DIR/docling.pid" ] && ps -p "$(cat "$PID_DIR/docling.pid")" > /dev/null 2>&1; then
        echo "docling already running (pid $(cat "$PID_DIR/docling.pid"))"
        return
    fi
    echo "Starting docling..."
    ./venv/bin/docling-serve run --port 5001 > "$LOG_DIR/docling.log" 2>&1 &
    echo $! > "$PID_DIR/docling.pid"
}

start_llama() {
    if [ -f "$PID_DIR/llama.pid" ] && ps -p "$(cat "$PID_DIR/llama.pid")" > /dev/null 2>&1; then
        echo "llama already running (pid $(cat "$PID_DIR/llama.pid"))"
        return
    fi
    echo "Starting llama..."
    ./llama.cpp/llama-server -m models/my-model.gguf --port 11434 > "$LOG_DIR/llama.log" 2>&1 &
    echo $! > "$PID_DIR/llama.pid"
}

start_rclone() {
    if [ -f "$PID_DIR/rclone.pid" ] && ps -p "$(cat "$PID_DIR/rclone.pid")" > /dev/null 2>&1; then
        echo "rclone already running (pid $(cat "$PID_DIR/rclone.pid"))"
        return
    fi
    echo "Starting rclone..."
    rclone mount gdrive: /data --vfs-cache-mode full > "$LOG_DIR/rclone.log" 2>&1 &
    echo $! > "$PID_DIR/rclone.pid"
}

# ---------- stop ----------
stop_qdrant() {
    echo "Stopping qdrant..."
    podman compose -f "$COMPOSE_FILE" stop qdrant
}

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

stop_docling() { stop_pidfile docling; }
stop_llama()   { stop_pidfile llama; }
stop_rclone()  { stop_pidfile rclone; }

# ---------- status ----------
status_qdrant() {
    podman compose -f "$COMPOSE_FILE" ps qdrant
}

status_pidfile() {
    local name="$1"
    local pidfile="$PID_DIR/$name.pid"
    if [ -f "$pidfile" ] && ps -p "$(cat "$pidfile")" > /dev/null 2>&1; then
        echo "$name is running (pid $(cat "$pidfile"))"
    else
        echo "$name is NOT running"
    fi
}

status_docling() { status_pidfile docling; }
status_llama()   { status_pidfile llama; }
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
