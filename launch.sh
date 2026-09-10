#!/bin/bash
# launch.sh

REPO_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
PID_DIR="$REPO_ROOT/.pids"
LOG_DIR="$REPO_ROOT/logs"
QDRANT_DIR="$REPO_ROOT/qdrant"
QDRANT_BIN="$QDRANT_DIR/qdrant"
QDRANT_DATA_DIR="$REPO_ROOT/qdrant_data"
QDRANT_PID_FILE="$PID_DIR/qdrant.pid"
QDRANT_LOCK_DIR="$PID_DIR/qdrant.lock"
QDRANT_LOG_FILE="$LOG_DIR/qdrant.log"
mkdir -p "$PID_DIR" "$LOG_DIR"

SERVICES=(qdrant ollama)

load_env_file() {
    local env_file="$REPO_ROOT/.env"
    if [ ! -f "$env_file" ]; then
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
    done < "$env_file"
}

pid_is_running() {
    local pid="$1"
    case "$pid" in
        ""|*[!0-9]*) return 1 ;;
    esac
    ps -p "$pid" > /dev/null 2>&1
}

pid_is_qdrant() {
    local pid="$1"
    if ! pid_is_running "$pid"; then
        return 1
    fi
    ps -p "$pid" -o command= 2>/dev/null | grep -q 'qdrant/qdrant'
}

read_pid_file() {
    local pidfile="$1"
    if [ -f "$pidfile" ]; then
        sed -n '1p' "$pidfile" 2>/dev/null
    fi
}

qdrant_host() {
    printf '%s\n' "${QDRANT_HOST:-http://localhost:6333}"
}

qdrant_ready() {
    local host
    host="$(qdrant_host)"
    curl -fsS --max-time 2 "$host/readyz" > /dev/null 2>&1 ||
        curl -fsS --max-time 2 "$host/" > /dev/null 2>&1
}

find_unmanaged_qdrant_pids() {
    if ! command -v pgrep > /dev/null 2>&1; then
        return 2
    fi
    local pids
    pids="$(pgrep -f 'qdrant/qdrant' 2>/dev/null)"
    local result=$?
    case "$result" in
        0) printf '%s\n' "$pids" ;;
        1) return 0 ;;
        *) return "$result" ;;
    esac
}

remove_qdrant_lock() {
    rm -f "$QDRANT_LOCK_DIR/owner.pid" 2>/dev/null || true
    rmdir "$QDRANT_LOCK_DIR" 2>/dev/null || true
}

acquire_qdrant_lock() {
    if mkdir "$QDRANT_LOCK_DIR" 2>/dev/null; then
        chmod 0775 "$QDRANT_LOCK_DIR" 2>/dev/null || true
        if ! (umask 0002; printf '%s\n' "$$" > "$QDRANT_LOCK_DIR/owner.pid"); then
            echo "ERROR: Unable to write Qdrant lock owner metadata." >&2
            remove_qdrant_lock
            return 1
        fi
        return 0
    fi

    local owner_pid
    owner_pid="$(read_pid_file "$QDRANT_LOCK_DIR/owner.pid")"
    if pid_is_running "$owner_pid"; then
        echo "ERROR: Qdrant startup/storage lock is held by pid $owner_pid." >&2
        return 1
    fi

    echo "Removing stale Qdrant lock${owner_pid:+ (pid $owner_pid)}."
    remove_qdrant_lock
    if ! mkdir "$QDRANT_LOCK_DIR" 2>/dev/null; then
        echo "ERROR: Unable to acquire Qdrant lock at $QDRANT_LOCK_DIR." >&2
        return 1
    fi
    chmod 0775 "$QDRANT_LOCK_DIR" 2>/dev/null || true
    if ! (umask 0002; printf '%s\n' "$$" > "$QDRANT_LOCK_DIR/owner.pid"); then
        echo "ERROR: Unable to write Qdrant lock owner metadata." >&2
        remove_qdrant_lock
        return 1
    fi
}

record_qdrant_pid() {
    local pid="$1"
    if ! (umask 0002; printf '%s\n' "$pid" > "$QDRANT_PID_FILE"); then
        return 1
    fi
    if ! (umask 0002; printf '%s\n' "$pid" > "$QDRANT_LOCK_DIR/owner.pid"); then
        rm -f "$QDRANT_PID_FILE"
        return 1
    fi
    chmod 0664 "$QDRANT_PID_FILE" "$QDRANT_LOCK_DIR/owner.pid" 2>/dev/null || true
}

cleanup_failed_qdrant_start() {
    local pid="$1"
    if ! pid_is_running "$pid"; then
        rm -f "$QDRANT_PID_FILE"
        remove_qdrant_lock
    fi
}

wait_for_qdrant() {
    local pid="$1"
    local timeout="${QDRANT_START_TIMEOUT:-600}"
    local interval="${QDRANT_START_INTERVAL:-2}"
    local elapsed=0

    while [ "$elapsed" -lt "$timeout" ]; do
        if qdrant_ready; then
            echo "qdrant is ready at $(qdrant_host) (pid $pid)"
            return 0
        fi
        if ! pid_is_running "$pid"; then
            echo "ERROR: Qdrant exited before becoming ready. Recent log output:" >&2
            tail -n 30 "$QDRANT_LOG_FILE" >&2 2>/dev/null || true
            cleanup_failed_qdrant_start "$pid"
            return 1
        fi
        if [ "$elapsed" -gt 0 ] && [ $((elapsed % 30)) -eq 0 ]; then
            echo "qdrant is still starting (pid $pid, ${elapsed}s elapsed)..."
        fi
        sleep "$interval"
        elapsed=$((elapsed + interval))
    done

    echo "ERROR: Qdrant pid $pid is still running but did not become ready within ${timeout}s." >&2
    echo "Inspect $QDRANT_LOG_FILE; the process and storage lock were left intact for diagnosis." >&2
    tail -n 30 "$QDRANT_LOG_FILE" >&2 2>/dev/null || true
    return 1
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
    local vlm_host="${VLM_BASE_URL:-$llm_host}"
    local embedding_host="${EMBEDDING_BASE_URL:-$ollama_host}"
    local llm_model="${LLM_MODEL:-}"
    local embedding_model="${EMBEDDING_MODEL:-}"

    ensure_ollama_model "$llm_model" "LLM_MODEL" "$llm_host"
    ensure_ollama_model "${VLM_MODEL:-}" "VLM_MODEL" "$vlm_host"
    ensure_ollama_model "$embedding_model" "EMBEDDING_MODEL" "$embedding_host"
}

# ---------- start ----------
start_qdrant() {
    load_env_file

    local managed_pid
    managed_pid="$(read_pid_file "$QDRANT_PID_FILE")"
    if qdrant_ready; then
        if pid_is_qdrant "$managed_pid"; then
            echo "qdrant is already ready at $(qdrant_host) (pid $managed_pid)"
        else
            echo "qdrant is already ready at $(qdrant_host) (externally managed)"
        fi
        return
    fi

    if pid_is_qdrant "$managed_pid"; then
        echo "qdrant is already running but not ready (pid $managed_pid)"
        return 1
    fi

    local unmanaged_pids
    if ! unmanaged_pids="$(find_unmanaged_qdrant_pids)"; then
        echo "ERROR: Unable to inspect existing Qdrant processes; refusing an unsafe start." >&2
        return 1
    fi
    if [ -n "$unmanaged_pids" ]; then
        echo "ERROR: Found unmanaged Qdrant process(es): $(printf '%s' "$unmanaged_pids" | tr '\n' ' ')." >&2
        echo "Refusing to start another process against shared storage. Reconcile or stop the existing process first." >&2
        return 1
    fi

    rm -f "$QDRANT_PID_FILE"
    if ! acquire_qdrant_lock; then
        return 1
    fi

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
            remove_qdrant_lock
            return 1
        fi

        echo "Downloading Qdrant from $URL ..."
        curl -L "$URL" | tar -xz -C "$QDRANT_DIR"
        if [ ! -x "$QDRANT_BIN" ]; then
            echo "ERROR: Failed to download or extract Qdrant."
            remove_qdrant_lock
            return 1
        fi
    fi

    local qdrant_nofile_limit="${QDRANT_NOFILE_LIMIT:-65536}"
    if ! ulimit -n "$qdrant_nofile_limit"; then
        echo "ERROR: Unable to raise the open-file limit to $qdrant_nofile_limit for Qdrant." >&2
        remove_qdrant_lock
        return 1
    fi

    echo "Starting qdrant with storage at $QDRANT_DATA_DIR..."
    mkdir -p "$QDRANT_DATA_DIR"
    printf '\n===== Qdrant start requested %s by %s (launcher pid %s) =====\n' \
        "$(date '+%Y-%m-%d %H:%M:%S %z')" "$(id -un)" "$$" >> "$QDRANT_LOG_FILE"
    (
        cd "$REPO_ROOT" || exit 1
        exec env QDRANT__STORAGE__STORAGE_PATH="$QDRANT_DATA_DIR" \
            "$QDRANT_BIN" >> "$QDRANT_LOG_FILE" 2>&1
    ) &
    local qdrant_pid=$!
    if ! record_qdrant_pid "$qdrant_pid"; then
        echo "ERROR: Unable to record Qdrant pid $qdrant_pid; stopping the unmanaged child." >&2
        kill "$qdrant_pid" 2>/dev/null || true
        wait "$qdrant_pid" 2>/dev/null || true
        remove_qdrant_lock
        return 1
    fi
    wait_for_qdrant "$qdrant_pid"
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

stop_qdrant()  {
    load_env_file
    local pid
    pid="$(read_pid_file "$QDRANT_PID_FILE")"

    if ! pid_is_running "$pid"; then
        if qdrant_ready; then
            echo "qdrant is ready at $(qdrant_host) but is not managed by this launcher; not stopping it." >&2
            return 1
        fi
        local unmanaged_pids
        if ! unmanaged_pids="$(find_unmanaged_qdrant_pids)"; then
            echo "ERROR: Unable to inspect existing Qdrant processes; refusing to alter service state." >&2
            return 1
        fi
        if [ -n "$unmanaged_pids" ]; then
            echo "qdrant process exists but is not managed by this launcher (pid(s): $(printf '%s' "$unmanaged_pids" | tr '\n' ' ')); not stopping it." >&2
            return 1
        fi
        echo "qdrant not running${pid:+ (stale pid $pid)}"
        rm -f "$QDRANT_PID_FILE"
        remove_qdrant_lock
        return
    fi

    if ! pid_is_qdrant "$pid"; then
        echo "ERROR: Refusing to stop pid $pid because it is not a Qdrant process; the PID file is stale." >&2
        return 1
    fi

    echo "Stopping qdrant (pid $pid)..."
    if ! kill "$pid" 2>/dev/null; then
        echo "ERROR: Unable to signal qdrant pid $pid; run stop as its owning user." >&2
        return 1
    fi
    local waited=0
    while pid_is_running "$pid" && [ "$waited" -lt 30 ]; do
        sleep 1
        waited=$((waited + 1))
    done
    if pid_is_running "$pid"; then
        echo "ERROR: qdrant pid $pid did not stop within 30s; PID and lock retained." >&2
        return 1
    fi
    rm -f "$QDRANT_PID_FILE"
    remove_qdrant_lock
}
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

status_qdrant()  {
    load_env_file
    local pid
    pid="$(read_pid_file "$QDRANT_PID_FILE")"
    if qdrant_ready; then
        if pid_is_qdrant "$pid"; then
            echo "qdrant is ready at $(qdrant_host) (pid $pid)"
        else
            echo "qdrant is ready at $(qdrant_host) (externally managed)"
        fi
    elif pid_is_qdrant "$pid"; then
        echo "qdrant is running but NOT ready (pid $pid)"
    else
        local unmanaged_pids
        if ! unmanaged_pids="$(find_unmanaged_qdrant_pids)"; then
            echo "qdrant readiness failed; process inspection is unavailable${pid:+ (stale managed pid $pid)}"
        elif [ -n "$unmanaged_pids" ]; then
            echo "qdrant process exists but is NOT ready and is not managed by this launcher (pid(s): $(printf '%s' "$unmanaged_pids" | tr '\n' ' '))"
        elif [ -n "$pid" ]; then
            echo "qdrant is NOT running (stale pid $pid)"
        else
            echo "qdrant is NOT running"
        fi
    fi
}
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
        local result=0
        for svc in "${SERVICES[@]}"; do
            "${action}_${svc}" || result=1
        done
        return "$result"
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
