#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_FILE="${SICTIC_RCLONE_CONFIG:-$SCRIPT_DIR/config.env}"

if [ ! -r "$CONFIG_FILE" ]; then
    echo "rclone sync is not configured: $CONFIG_FILE" >&2
    echo "Run $SCRIPT_DIR/configure.sh first." >&2
    exit 78
fi

# config.env is a private, user-owned shell file written by configure.sh.
# shellcheck disable=SC1090
source "$CONFIG_FILE"

RCLONE_BIN="${RCLONE_BIN:-$(command -v rclone || true)}"
LOCAL_ROOT="${RCLONE_LOCAL_ROOT:-}"
REMOTE_ROOT="${RCLONE_REMOTE_ROOT:-}"
WORK_DIR="${RCLONE_WORK_DIR:-$SCRIPT_DIR/state}"
LOG_DIR="${RCLONE_RUN_LOG_DIR:-$SCRIPT_DIR/logs}"
CENTRAL_LOG="${RCLONE_CENTRAL_LOG:-$REPO_ROOT/logs/rclone.log}"
FILTERS_FILE="${RCLONE_FILTERS_FILE:-$SCRIPT_DIR/filters.txt}"
LOCK_DIR="${RCLONE_LOCK_DIR:-$SCRIPT_DIR/run.lock}"
CHECK_FILENAME="${RCLONE_CHECK_FILENAME:-RCLONE_TEST}"
MAX_DELETE="${RCLONE_MAX_DELETE:-10}"

usage() {
    echo "usage: $0 bootstrap-dry-run|bootstrap|recover-from-drive|dry-run|sync" >&2
    exit 64
}

[ "$#" -eq 1 ] || usage
MODE="$1"

[ -n "$RCLONE_BIN" ] && [ -x "$RCLONE_BIN" ] || {
    echo "rclone was not found on PATH; see $SCRIPT_DIR/README.md" >&2
    exit 69
}
[ -n "$LOCAL_ROOT" ] || {
    echo "RCLONE_LOCAL_ROOT is missing from $CONFIG_FILE" >&2
    exit 78
}
[ -n "$REMOTE_ROOT" ] || {
    echo "RCLONE_REMOTE_ROOT is missing from $CONFIG_FILE" >&2
    exit 78
}
[ -d "$LOCAL_ROOT" ] || {
    echo "local root not found: $LOCAL_ROOT" >&2
    exit 72
}
[ -r "$FILTERS_FILE" ] || {
    echo "filters file not readable: $FILTERS_FILE" >&2
    exit 72
}

if [ -n "${RCLONE_CONFIG_FILE:-}" ]; then
    [ -r "$RCLONE_CONFIG_FILE" ] || {
        echo "rclone config not readable: $RCLONE_CONFIG_FILE" >&2
        exit 78
    }
fi

mkdir -p "$WORK_DIR" "$LOG_DIR" "$(dirname "$CENTRAL_LOG")"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "another rclone sync appears to be running: $LOCK_DIR" >&2
    exit 75
fi
printf '%s\n' "$$" > "$LOCK_DIR/pid"

TIMESTAMP="$(date '+%Y%m%d-%H%M%S')"
LOG_FILE="$LOG_DIR/$TIMESTAMP-$MODE.log"

# Keep one continuous operational log and one immutable log per invocation.
# Plain file descriptors work in restricted agent environments where Bash
# process substitution through /dev/fd is unavailable.
exec 3>&1 4>&2
exec >"$LOG_FILE" 2>&1
echo "===== rclone $MODE started $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
echo "local=$LOCAL_ROOT remote=$REMOTE_ROOT pid=$$"

finish() {
    exit_code=$?
    set +e
    if [ "$exit_code" -eq 0 ]; then
        outcome=completed
    else
        outcome="failed exit=$exit_code"
    fi
    echo "===== rclone $MODE $outcome $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
    echo "central log: $CENTRAL_LOG"
    echo "run log: $LOG_FILE"
    rm -f "$LOCK_DIR/pid"
    rmdir "$LOCK_DIR" 2>/dev/null || true
    cat "$LOG_FILE" >> "$CENTRAL_LOG"
    cat "$LOG_FILE" >&3
    exec 3>&- 4>&-
    return "$exit_code"
}
trap finish EXIT
trap 'exit 130' INT TERM HUP

COMMON_ARGS=(
    --color NEVER
    --check-filename "$CHECK_FILENAME"
    --no-update-dir-modtime
    --drive-import-formats md
    --drive-export-formats md
    --filters-file "$FILTERS_FILE"
    --suffix-keep-extension
    --conflict-resolve none
    --conflict-loser num
    --max-delete "$MAX_DELETE"
    --resilient
    --recover
    --create-empty-src-dirs
    --workdir "$WORK_DIR"
    --log-level "${RCLONE_LOG_LEVEL:-INFO}"
    --log-format date,time,microseconds,longfile
    --stats 30s
    --stats-one-line-date
)
if [ -n "${RCLONE_CONFIG_FILE:-}" ]; then
    COMMON_ARGS+=(--config "$RCLONE_CONFIG_FILE")
fi

CHECK_FILE="$LOCAL_ROOT/$CHECK_FILENAME"

case "$MODE" in
    bootstrap-dry-run)
        "$RCLONE_BIN" bisync "$LOCAL_ROOT" "$REMOTE_ROOT" \
            --resync --dry-run "${COMMON_ARGS[@]}"
        ;;
    bootstrap)
        # The marker is copied to Drive by the first baseline operation and is
        # required on both roots by every routine run.
        touch "$CHECK_FILE"
        "$RCLONE_BIN" bisync "$LOCAL_ROOT" "$REMOTE_ROOT" \
            --resync "${COMMON_ARGS[@]}"
        ;;
    recover-from-drive)
        [ -f "$CHECK_FILE" ] || {
            echo "missing safety marker: $CHECK_FILE" >&2
            exit 66
        }
        "$RCLONE_BIN" bisync "$LOCAL_ROOT" "$REMOTE_ROOT" \
            --check-access --resync-mode path2 "${COMMON_ARGS[@]}"
        ;;
    dry-run)
        [ -f "$CHECK_FILE" ] || {
            echo "missing safety marker: $CHECK_FILE; run bootstrap first" >&2
            exit 66
        }
        "$RCLONE_BIN" bisync "$LOCAL_ROOT" "$REMOTE_ROOT" \
            --check-access --dry-run "${COMMON_ARGS[@]}"
        ;;
    sync)
        [ -f "$CHECK_FILE" ] || {
            echo "missing safety marker: $CHECK_FILE; run bootstrap first" >&2
            exit 66
        }
        "$RCLONE_BIN" bisync "$LOCAL_ROOT" "$REMOTE_ROOT" \
            --check-access "${COMMON_ARGS[@]}"
        ;;
    *)
        usage
        ;;
esac
