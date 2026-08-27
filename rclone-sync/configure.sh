#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_FILE="${SICTIC_RCLONE_CONFIG:-$SCRIPT_DIR/config.env}"
LOCAL_ROOT=""
REMOTE_ROOT=""

usage() {
    cat <<EOF
usage: $0 [--local-root PATH] [--remote REMOTE:PATH]

Creates the private rclone-sync/config.env used by rclone-sync.sh.
The rclone remote itself remains user-owned and is created with rclone config.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --local-root) LOCAL_ROOT="$2"; shift 2 ;;
        --remote) REMOTE_ROOT="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage >&2; exit 64 ;;
    esac
done

RCLONE_BIN="${RCLONE_BIN:-$(command -v rclone || true)}"
if [ -z "$RCLONE_BIN" ]; then
    cat >&2 <<'EOF'
rclone is not installed.

macOS with Homebrew:
  brew install rclone

Linux or WSL2 (official installer; review before running):
  sudo -v
  curl https://rclone.org/install.sh | sudo bash

Then rerun this configuration command.
EOF
    exit 69
fi

if ! "$RCLONE_BIN" bisync --help 2>/dev/null | grep -q -- '--recover'; then
    echo "this rclone version is too old for the configured bisync safeguards; update rclone first" >&2
    exit 69
fi

run_rclone() {
    if [ -n "${RCLONE_CONFIG_FILE:-}" ]; then
        "$RCLONE_BIN" --config "$RCLONE_CONFIG_FILE" "$@"
    else
        "$RCLONE_BIN" "$@"
    fi
}

env_value() {
    key="$1"
    path="$2"
    [ -f "$path" ] || return 0
    awk -F= -v k="$key" '
        $0 ~ "^[[:space:]]*" k "[[:space:]]*=" {
            value=$0
            sub("^[^=]*=", "", value)
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
            if ((value ~ /^".*"$/) || (value ~ /^\047.*\047$/)) {
                value=substr(value, 2, length(value)-2)
            }
            print value
            exit
        }
    ' "$path"
}

if [ -z "$LOCAL_ROOT" ]; then
    storage_root="$(env_value LOCAL_STORAGE_PATH "$REPO_ROOT/.env" || true)"
    if [ -z "$storage_root" ]; then
        storage_root="$REPO_ROOT/local_storage"
    fi
    default_local="$storage_root/storage"
    if [ -t 0 ]; then
        read -r -p "Local storage tree [$default_local]: " LOCAL_ROOT
    fi
    LOCAL_ROOT="${LOCAL_ROOT:-$default_local}"
fi

if [ ! -d "$LOCAL_ROOT" ]; then
    echo "local storage tree does not exist: $LOCAL_ROOT" >&2
    echo "Create it or pass the correct path with --local-root." >&2
    exit 72
fi
LOCAL_ROOT="$(cd "$LOCAL_ROOT" && pwd)"

if [ -z "$REMOTE_ROOT" ]; then
    remotes="$(run_rclone listremotes)"
    if [ -z "$remotes" ]; then
        if [ ! -t 0 ]; then
            echo "no rclone remotes are configured; run 'rclone config' first" >&2
            exit 78
        fi
        read -r -p "No rclone remotes exist. Run 'rclone config' now? [Y/n]: " answer
        case "$answer" in
            n|N|no|NO) exit 78 ;;
            *) run_rclone config ;;
        esac
        remotes="$(run_rclone listremotes)"
    fi
    echo "Configured rclone remotes:"
    printf '%s\n' "$remotes"
    if [ -t 0 ]; then
        read -r -p "Google Drive destination (for example, gdrive:SICTIC-AI): " REMOTE_ROOT
    fi
fi

case "$REMOTE_ROOT" in
    *:*) ;;
    *) echo "remote must use rclone syntax REMOTE:PATH" >&2; exit 64 ;;
esac

REMOTE_NAME="${REMOTE_ROOT%%:*}"
if ! run_rclone listremotes | grep -Fxq "$REMOTE_NAME:"; then
    echo "rclone remote '$REMOTE_NAME' is not configured; run 'rclone config'" >&2
    exit 78
fi

REMOTE_TYPE="$(run_rclone config redacted "$REMOTE_NAME" 2>/dev/null | awk -F= '
    /^[[:space:]]*type[[:space:]]*=/ {
        value=$2
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
        print value
        exit
    }
')"
if [ "$REMOTE_TYPE" != "drive" ]; then
    echo "remote '$REMOTE_NAME' uses backend '$REMOTE_TYPE'; this helper requires Google Drive" >&2
    exit 78
fi

if ! run_rclone lsf "$REMOTE_ROOT" --max-depth 1 >/dev/null 2>&1; then
    echo "Google Drive path does not exist or is not accessible: $REMOTE_ROOT" >&2
    echo "Create it explicitly with: rclone mkdir '$REMOTE_ROOT'" >&2
    exit 72
fi

umask 077
tmp="$OUTPUT_FILE.tmp.$$"
{
    printf 'RCLONE_LOCAL_ROOT=%q\n' "$LOCAL_ROOT"
    printf 'RCLONE_REMOTE_ROOT=%q\n' "$REMOTE_ROOT"
    if [ -n "${RCLONE_CONFIG_FILE:-}" ]; then
        printf 'RCLONE_CONFIG_FILE=%q\n' "$RCLONE_CONFIG_FILE"
    fi
} > "$tmp"
mv "$tmp" "$OUTPUT_FILE"

echo
echo "Saved Google Drive synchronization configuration to $OUTPUT_FILE"
echo "Local:  $LOCAL_ROOT"
echo "Remote: $REMOTE_ROOT"
echo
echo "Next, inspect the initial baseline without changing files:"
echo "  $SCRIPT_DIR/rclone-sync.sh bootstrap-dry-run"
