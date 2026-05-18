#!/bin/sh
# install_skills_conda.sh — conda-based variant of install_skills.sh.
#
# Identical end result to install_skills.sh, but the Python environment is
# provisioned via conda using environment.yml instead of a per-repo venv.
# Prerequisite: `conda` must be on PATH. Install via:
#     brew install --cask miniforge
#     conda init zsh   # (or bash) — restart shell after this
#
# What it does:
#   1. Ensures the conda env named in environment.yml exists. If not, creates
#      it from environment.yml. If yes, updates it from environment.yml with
#      --prune (removes deps no longer listed).
#   2. Resolves the env's python path and runs `pip install -e .` inside it.
#   3. Mirrors every skills/<name>/ that has a SKILL.md into <target>/<name>/,
#      substituting:
#         {{REPO_ROOT}}/venv/bin/python  ->  <conda env python absolute path>
#         {{REPO_ROOT}}                  ->  <repo absolute path>
#      so SKILL.md commands work without conda activation.
#
# This script never touches ~/.openclaw/openclaw.json or any other openclaw
# config — only the conda env, the mirror target, and (transitively)
# pyproject.toml / environment.yml.
#
# Usage:
#   ./install_skills_conda.sh --target /path/to/openclaw/skill/dir   # required
#   ./install_skills_conda.sh --target ... --symlink                 # symlink mirrors instead of copy
#   ./install_skills_conda.sh --target ... --prune                   # remove target subdirs no longer in source
#   ./install_skills_conda.sh --target ... --rebuild-env             # force a fresh conda env (env remove + create)
#   ./install_skills_conda.sh --target ... --skip-env                # skip steps 1+2 (mirror only)

set -eu

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
TARGET=""
ENV_FILE="$REPO_ROOT/environment.yml"
MODE="copy"
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
        --symlink) MODE="symlink"; shift ;;
        --prune) PRUNE=1; shift ;;
        --rebuild-env) REBUILD_ENV=1; shift ;;
        --skip-env) SKIP_ENV=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
    esac
done

if [ -z "$TARGET" ]; then
    echo "install_skills_conda: --target is required." >&2
    usage
    exit 2
fi
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
echo "  mode:     $MODE"
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

    # Resolve the env's python path. `conda run -n X which python` is the
    # most reliable approach (doesn't depend on knowing CONDA_PREFIX layout).
    ENV_PY=$(conda run -n "$ENV_NAME" --no-capture-output which python | tail -1 | tr -d '\r')
    if [ -z "$ENV_PY" ] || [ ! -x "$ENV_PY" ]; then
        echo "install_skills_conda: could not resolve python path in '$ENV_NAME'." >&2
        exit 1
    fi

    echo "[2/3] pip install -e . (inside conda env $ENV_NAME)..."
    # environment.yml already lists `-e .` in its pip: section, so this is
    # idempotent. We re-run it explicitly to pick up any pyproject.toml change
    # that landed since the env was last touched (without rebuilding the env).
    "$ENV_PY" -m pip install --quiet -e "$REPO_ROOT"
else
    echo "[1+2/3] conda env: skipped (--skip-env)"
    ENV_PY=$(conda run -n "$ENV_NAME" --no-capture-output which python 2>/dev/null | tail -1 | tr -d '\r' || true)
    if [ -z "$ENV_PY" ] || [ ! -x "$ENV_PY" ]; then
        echo "install_skills_conda: --skip-env requested but env '$ENV_NAME' has no usable python." >&2
        exit 1
    fi
fi

echo "  env python: $ENV_PY"

# ---------------------------------------------------------------------------
# Step 3: mirror skills + substitute {{REPO_ROOT}} placeholder
# ---------------------------------------------------------------------------
echo "[3/3] Mirroring skills into $TARGET ..."
mkdir -p "$TARGET"

INSTALLED_LIST=""
installed_count=0

for src in "$REPO_ROOT/skills"/*/; do
    src="${src%/}"
    name=$(basename "$src")
    [ -f "$src/SKILL.md" ] || continue

    dst="$TARGET/$name"
    rm -rf "$dst"

    if [ "$MODE" = "symlink" ]; then
        ln -s "$src" "$dst"
    else
        cp -R "$src" "$dst"
        find "$dst" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
        if [ -f "$dst/SKILL.md" ]; then
            # Replace the venv-style python prefix with the actual conda env python
            # BEFORE the generic {{REPO_ROOT}} substitution, so the python path
            # comes out as <conda_env_python_abs>, not <repo>/venv/bin/python.
            sed -i.bak \
                -e "s|{{REPO_ROOT}}/venv/bin/python|$ENV_PY|g" \
                -e "s|{{REPO_ROOT}}|$REPO_ROOT|g" \
                "$dst/SKILL.md"
            rm -f "$dst/SKILL.md.bak"
        fi
    fi

    INSTALLED_LIST="$INSTALLED_LIST $name"
    installed_count=$((installed_count + 1))
    echo "       + $name"
done

cat > "$TARGET/_SICTIC_AI.md" <<EOF
# SICTIC-AI skills (installed from $REPO_ROOT, conda variant)

These skill directories were mirrored from \`$REPO_ROOT/skills/\` by:

    $REPO_ROOT/install_skills_conda.sh

Re-run that command after editing SKILL.md or moving the repo.

## Invocation

Each SKILL.md "Usage" section contains absolute, copy-pastable commands of the form:

    $ENV_PY -m skills.<skill_name> [args...]

Run them exactly as written. No \`conda activate\` needed — the absolute python
path resolves to the conda env directly.
EOF

if [ "$PRUNE" -eq 1 ]; then
    echo "       Pruning target subdirs not present in source..."
    for d in "$TARGET"/*/; do
        [ -d "$d" ] || continue
        name=$(basename "$d")
        case " $INSTALLED_LIST " in
            *" $name "*) ;;
            *) echo "       - $name"; rm -rf "$d" ;;
        esac
    done
fi

echo "       Installed $installed_count skill(s)."

echo
echo "Done."
