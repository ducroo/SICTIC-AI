#!/bin/sh
# install_skills_conda.sh — conda-based installer for SICTIC-AI.
#
# Prerequisite: `conda` must be on PATH. Install via:
#     brew install --cask miniforge
#     conda init zsh   # (or bash) — restart shell after this
#
# What it does:
#   1. Ensures the conda env named in environment.yml exists. If not, creates it.
#      If yes, updates it with --prune (removes deps no longer listed).
#   2. Runs `pip install -e .` inside the conda environment.
#   3. Symlinks every skills/<name>/ that has a SKILL.md into <target>/<name>/.
#      Crucially, it skips any existing real directories in the target to prevent
#      accidentally deleting user-created skills before they are ingested.
#
# Usage:
#   ./install_skills_conda.sh --target /path/to/openclaw/skill/dir   # required
#   ./install_skills_conda.sh --target ... --prune                   # remove broken target symlinks
#   ./install_skills_conda.sh --target ... --rebuild-env             # force a fresh conda env
#   ./install_skills_conda.sh --target ... --skip-env                # skip steps 1+2 (symlink only)

set -eu

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
TARGET=""
ENV_FILE="$REPO_ROOT/environment.yml"
PRUNE=0
REBUILD_ENV=0
SKIP_ENV=0

usage() {
    sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
    case "$1" in
        --target) TARGET="$2"; shift 2 ;;
        --source) REPO_ROOT="$(cd "$2" && pwd)"; ENV_FILE="$REPO_ROOT/environment.yml"; shift 2 ;;
        --prune) PRUNE=1; shift ;;
        --rebuild-env) REBUILD_ENV=1; shift ;;
        --skip-env) SKIP_ENV=1; shift ;;
        --symlink) shift ;; # Kept for backwards compatibility, silently ignored (now default)
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
    esac
done

if [ -z "$TARGET" ]; then
    echo "install_skills_conda: --target is required." >&2
    usage
    exit 2
fi

# Ensure TARGET resolves to an absolute path for symlinks
mkdir -p "$TARGET"
TARGET="$(cd "$TARGET" && pwd)"

if [ ! -d "$REPO_ROOT/skills" ]; then
    echo "install_skills_conda: $REPO_ROOT/skills not found." >&2
    exit 1
fi
if [ ! -f "$REPO_ROOT/pyproject.toml" ]; then
    echo "install_skills_conda: $REPO_ROOT/pyproject.toml not found." >&2
    exit 1
fi
if [ ! -f "$ENV_FILE" ]; then
    echo "install_skills_conda: $ENV_FILE not found." >&2
    exit 1
fi
if ! command -v conda >/dev/null 2>&1; then
    echo "install_skills_conda: 'conda' not on PATH. Install miniforge first:" >&2
    echo "    brew install --cask miniforge" >&2
    echo "    conda init zsh   # then restart your shell" >&2
    exit 127
fi

# ---------------------------------------------------------------------------
# Read the env name from environment.yml (line `name: <env_name>`).
# Avoids depending on yq/python at this point.
# ---------------------------------------------------------------------------
ENV_NAME=$(awk -F: '/^name:[[:space:]]*/ { gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2); print $2; exit }' "$ENV_FILE")
if [ -z "$ENV_NAME" ]; then
    echo "install_skills_conda: could not read 'name:' from $ENV_FILE." >&2
    exit 1
fi

echo "Installing SICTIC-AI (conda variant)"
echo "  source:   $REPO_ROOT"
echo "  target:   $TARGET"
echo "  env name: $ENV_NAME"
echo "  env file: $ENV_FILE"
echo

# ---------------------------------------------------------------------------
# Step 1+2: conda env bootstrap + editable install
# ---------------------------------------------------------------------------
if [ "$SKIP_ENV" -eq 0 ]; then
    env_exists=0
    if conda env list 2>/dev/null | awk '{print $1}' | grep -qx "$ENV_NAME"; then
        env_exists=1
    fi

    if [ "$env_exists" -eq 1 ] && [ "$REBUILD_ENV" -eq 1 ]; then
        echo "[1/3] conda env: --rebuild-env — removing existing '$ENV_NAME'..."
        conda env remove -n "$ENV_NAME" --yes >/dev/null
        env_exists=0
    fi

    if [ "$env_exists" -eq 0 ]; then
        echo "[1/3] conda env: creating '$ENV_NAME' from $ENV_FILE..."
        conda env create -n "$ENV_NAME" -f "$ENV_FILE"
    else
        echo "[1/3] conda env: '$ENV_NAME' present — updating from $ENV_FILE (with --prune)..."
        conda env update -n "$ENV_NAME" -f "$ENV_FILE" --prune
    fi

    ENV_PY=$(conda run -n "$ENV_NAME" --no-capture-output which python | tail -1 | tr -d '\r')
    if [ -z "$ENV_PY" ] || [ ! -x "$ENV_PY" ]; then
        echo "install_skills_conda: could not resolve python path in '$ENV_NAME'." >&2
        exit 1
    fi

    echo "[2/3] pip install -e . (inside conda env $ENV_NAME)..."
    "$ENV_PY" -m pip install --quiet -e "$REPO_ROOT"
else
    echo "[1+2/3] conda env: skipped (--skip-env)"
    ENV_PY=$(conda run -n "$ENV_NAME" --no-capture-output which python 2>/dev/null | tail -1 | tr -d '\r' || true)
    if [ -z "$ENV_PY" ] || [ ! -x "$ENV_PY" ]; then
        echo "install_skills_conda: --skip-env requested but env '$ENV_NAME' has no usable python." >&2
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# Step 3: symlink skills
# ---------------------------------------------------------------------------
echo "[3/3] Symlinking skills into $TARGET ..."

INSTALLED_LIST=""
installed_count=0

for src in "$REPO_ROOT/skills"/*/; do
    src="${src%/}"
    name=$(basename "$src")
    [ -f "$src/SKILL.md" ] || continue

    dst="$TARGET/$name"

    # SAFETY CHECK: Never delete a real directory (could be an un-ingested user skill)
    if [ -d "$dst" ] && [ ! -L "$dst" ]; then
        echo "       ! Skipping $name (real directory detected. Use sictic_git_sync to ingest)"
        continue
    fi

    rm -f "$dst" # Safely remove symlink if it exists
    ln -s "$src" "$dst"

    INSTALLED_LIST="$INSTALLED_LIST $name "
    installed_count=$((installed_count + 1))
    echo "       + $name"
done

cat > "$TARGET/_SICTIC_AI.md" <<EOF
# SICTIC-AI skills

These skill directories are symlinked to \`$REPO_ROOT/skills/\` by:

    $REPO_ROOT/install_skills_conda.sh

Any edits made here will directly edit the Git repository.

## Invocation

Each SKILL.md "Usage" section contains universal conda run commands.
EOF

if [ "$PRUNE" -eq 1 ]; then
    echo "       Pruning target subdirs not present in source..."
    for d in "$TARGET"/*/; do
        [ -d "$d" ] || continue
        name=$(basename "$d")
        
        # SAFETY CHECK: Only prune symlinks, never prune real directories
        if [ -d "$d" ] && [ ! -L "$d" ]; then
            continue
        fi

        case " $INSTALLED_LIST " in
            *" $name "*) ;;
            *) echo "       - $name"; rm -f "$d" ;;
        esac
    done
fi

echo "       Installed $installed_count skill(s)."

echo
echo "Done."