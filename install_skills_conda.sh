#!/bin/sh
# install_skills_conda.sh — conda-based installer for SICTIC-AI.
#
# Prerequisite: `conda` must be on PATH.
#   macOS:
#     brew install --cask miniforge
#     conda init zsh   # or bash
#   Linux/WSL2:
#     curl -L -O "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"
#     bash Miniforge3-*.sh
#     conda init bash  # or zsh
#   Restart the shell after initializing conda.
#
# What it does:
#   1. Ensures the conda env named in environment.yml exists. If not, creates it.
#      If yes, updates it with --prune (removes deps no longer listed).
#   2. Registers the repository root in the environment's site-packages using
#      a generated .pth file, without invoking project dependency resolution.
#   3. Copies every skills/<name>/ that has a SKILL.md into <target>/<name>/.
#      Existing files with the same name are overwritten; extra files already in
#      the target are left alone.
#
# Usage:
#   ./install_skills_conda.sh --target /path/to/openclaw/skill/dir   # required
#   ./install_skills_conda.sh --target ... --rebuild-env             # force a fresh conda env
#   ./install_skills_conda.sh --target ... --skip-env                # skip steps 1+2 (copy only)
#   ./install_skills_conda.sh --target ... --non-interactive          # do not prompt for .env values

set -eu

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
TARGET=""
ENV_FILE="$REPO_ROOT/environment.yml"
REBUILD_ENV=0
SKIP_ENV=0
INTERACTIVE=1

usage() {
    sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
    case "$1" in
        --target) TARGET="$2"; shift 2 ;;
        --source) REPO_ROOT="$(cd "$2" && pwd)"; ENV_FILE="$REPO_ROOT/environment.yml"; shift 2 ;;
        --prune) shift ;; # Kept for backwards compatibility; copy installs do not prune.
        --rebuild-env) REBUILD_ENV=1; shift ;;
        --skip-env) SKIP_ENV=1; shift ;;
        --non-interactive) INTERACTIVE=0; shift ;;
        --symlink) shift ;; # Kept for backwards compatibility; installs now copy skill files.
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
    esac
done

if [ -z "$TARGET" ]; then
    echo "install_skills_conda: --target is required." >&2
    usage
    exit 2
fi

# Ensure TARGET resolves to an absolute path for user-facing metadata.
mkdir -p "$TARGET"
TARGET="$(cd "$TARGET" && pwd)"

if [ ! -d "$REPO_ROOT/skills" ]; then
    echo "install_skills_conda: $REPO_ROOT/skills not found." >&2
    exit 1
fi
if [ ! -f "$ENV_FILE" ]; then
    echo "install_skills_conda: $ENV_FILE not found." >&2
    exit 1
fi
if ! command -v conda >/dev/null 2>&1; then
    echo "install_skills_conda: 'conda' not on PATH. Install Miniforge first:" >&2
    echo "  macOS:" >&2
    echo "    brew install --cask miniforge" >&2
    echo "    conda init zsh   # or bash; then restart your shell" >&2
    echo "  Linux/WSL2:" >&2
    echo "    curl -L -O \"https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-\$(uname)-\$(uname -m).sh\"" >&2
    echo "    bash Miniforge3-*.sh" >&2
    echo "    conda init bash  # or zsh; then restart your shell" >&2
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
DESIRED_PYTHON=$(awk -F= '/^[[:space:]]*-[[:space:]]*python=/ { gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2); print $2; exit }' "$ENV_FILE")

active_conda_env() {
    if [ -n "${CONDA_DEFAULT_ENV:-}" ]; then
        printf '%s\n' "$CONDA_DEFAULT_ENV"
        return
    fi
    if [ -n "${CONDA_PREFIX:-}" ]; then
        basename "$CONDA_PREFIX"
    fi
}

require_env_not_active_for_rebuild() {
    active_env=$(active_conda_env)
    if [ "$REBUILD_ENV" -eq 1 ] && [ "$active_env" = "$ENV_NAME" ]; then
        echo "install_skills_conda: cannot rebuild '$ENV_NAME' while it is the active conda environment." >&2
        echo >&2
        echo "Run this first:" >&2
        echo "    conda deactivate" >&2
        echo >&2
        echo "Then rerun the installer:" >&2
        echo "    $0 --target \"$TARGET\" --rebuild-env" >&2
        exit 1
    fi
}

copy_skill_dir() {
    src_dir="$1"
    dst_dir="$2"

    mkdir -p "$dst_dir"
    (
        cd "$src_dir"
        find . \
            \( -name __pycache__ -o -name .DS_Store -o -name '*.pyc' \) -prune \
            -o -type d -exec mkdir -p "$dst_dir/{}" \; \
            -o -type f -exec cp "{}" "$dst_dir/{}" \;
    )
}

echo "Installing SICTIC-AI (conda variant)"
echo "  source:   $REPO_ROOT"
echo "  target:   $TARGET"
echo "  env name: $ENV_NAME"
echo "  env file: $ENV_FILE"
echo

# ---------------------------------------------------------------------------
# Step 1+2: conda env bootstrap + repository import path
# ---------------------------------------------------------------------------
if [ "$SKIP_ENV" -eq 0 ]; then
    env_exists=0
    if conda env list 2>/dev/null | awk '{print $1}' | grep -qx "$ENV_NAME"; then
        env_exists=1
    fi

    require_env_not_active_for_rebuild

    if [ "$env_exists" -eq 1 ] && [ "$REBUILD_ENV" -eq 1 ]; then
        echo "[1/3] conda env: --rebuild-env — removing existing '$ENV_NAME'..."
        conda env remove -n "$ENV_NAME" --yes >/dev/null
        env_exists=0
    fi

    if [ "$env_exists" -eq 1 ] && [ -n "$DESIRED_PYTHON" ]; then
        CURRENT_PYTHON=$(conda run -n "$ENV_NAME" python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null | tail -1 | tr -d '\r' || true)
        if [ -n "$CURRENT_PYTHON" ] && [ "$CURRENT_PYTHON" != "$DESIRED_PYTHON" ]; then
            echo "[1/3] conda env: '$ENV_NAME' uses Python $CURRENT_PYTHON, but $ENV_FILE requires Python $DESIRED_PYTHON."
            if [ "$INTERACTIVE" -eq 1 ]; then
                printf "Rebuild conda env '$ENV_NAME' now? This replaces the env but keeps project files and .env. [y/N]: "
                IFS= read -r rebuild_answer || rebuild_answer=""
                case "$rebuild_answer" in
                    y|Y|yes|YES)
                        REBUILD_ENV=1
                        require_env_not_active_for_rebuild
                        conda env remove -n "$ENV_NAME" --yes >/dev/null
                        env_exists=0
                        ;;
                    *)
                        echo "install_skills_conda: rebuild required for the pinned Docling runtime. Re-run with --rebuild-env when ready." >&2
                        exit 1
                        ;;
                esac
            else
                echo "install_skills_conda: rebuild required for Python $DESIRED_PYTHON. Re-run with --rebuild-env." >&2
                exit 1
            fi
        fi
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

else
    echo "[1+2/3] conda env: skipped (--skip-env)"
    ENV_PY=$(conda run -n "$ENV_NAME" --no-capture-output which python 2>/dev/null | tail -1 | tr -d '\r' || true)
    if [ -z "$ENV_PY" ] || [ ! -x "$ENV_PY" ]; then
        echo "install_skills_conda: --skip-env requested but env '$ENV_NAME' has no usable python." >&2
        exit 1
    fi
fi

echo "[2/3] Registering repository import path in $ENV_NAME..."
"$ENV_PY" -m pip uninstall --yes sictic-skills >/dev/null 2>&1 || true
SITE_PACKAGES=$("$ENV_PY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
if [ -z "$SITE_PACKAGES" ] || [ ! -d "$SITE_PACKAGES" ]; then
    echo "install_skills_conda: could not resolve site-packages in '$ENV_NAME'." >&2
    exit 1
fi
printf '%s\n' "$REPO_ROOT" > "$SITE_PACKAGES/sictic-ai-repo.pth"

# ---------------------------------------------------------------------------
# Step 3: copy skills
# ---------------------------------------------------------------------------
echo "[3/3] Copying skills into $TARGET ..."

INSTALLED_LIST=""
installed_count=0

for src in "$REPO_ROOT/skills"/*/; do
    src="${src%/}"
    name=$(basename "$src")
    [ -f "$src/SKILL.md" ] || continue

    dst="$TARGET/$name"

    if [ -L "$dst" ]; then
        echo "       ! Skipping $name (target is a symlink; delete it manually before reinstalling)"
        continue
    fi

    copy_skill_dir "$src" "$dst"

    INSTALLED_LIST="$INSTALLED_LIST $name "
    installed_count=$((installed_count + 1))
    echo "       + $name"
done

cat > "$TARGET/_SICTIC_AI.md" <<EOF
# SICTIC-AI skills

These skill directories are copied from \`$REPO_ROOT/skills/\` by:

    $REPO_ROOT/install_skills_conda.sh

The installer registers \`$REPO_ROOT\` in the \`$ENV_NAME\` conda environment,
so harness commands execute repository code even though these instruction
folders are copied. Runtime dependencies come only from \`environment.yml\`.

## Invocation

Each SKILL.md "Usage" section contains a harness slash command.
EOF

echo "       Installed $installed_count skill(s)."

# ---------------------------------------------------------------------------
# Step 4: interactive .env setup
# ---------------------------------------------------------------------------
ENV_PATH="$REPO_ROOT/.env"
ENV_TEMPLATE="$REPO_ROOT/.env-template"
ENV_CREATED=0

env_get() {
    key="$1"
    if [ ! -f "$ENV_PATH" ]; then
        return 0
    fi
    awk -F= -v k="$key" '
        $0 ~ "^[[:space:]]*" k "[[:space:]]*=" {
            val=$0
            sub("^[^=]*=", "", val)
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", val)
            if ((val ~ /^".*"$/) || (val ~ /^\047.*\047$/)) {
                val=substr(val, 2, length(val)-2)
            }
            print val
            exit
        }
    ' "$ENV_PATH"
}

env_set() {
    key="$1"
    value="$2"
    tmp="$ENV_PATH.tmp.$$"
    escaped=$(printf '%s' "$value" | sed 's/[\/&]/\\&/g')
    if grep -q "^[[:space:]]*$key[[:space:]]*=" "$ENV_PATH"; then
        sed "s/^\\([[:space:]]*$key[[:space:]]*=\\).*/\\1$escaped/" "$ENV_PATH" > "$tmp"
    else
        cp "$ENV_PATH" "$tmp"
        printf '%s=%s\n' "$key" "$value" >> "$tmp"
    fi
    mv "$tmp" "$ENV_PATH"
}

ask_env() {
    key="$1"
    prompt="$2"
    default="$3"
    required="$4"
    secret="$5"
    current=$(env_get "$key" || true)
    shown_default="$current"
    if [ -z "$shown_default" ]; then
        shown_default="$default"
    fi

    while :; do
        if [ "$secret" -eq 1 ] && [ -n "$shown_default" ]; then
            printf '%s [%s]: ' "$prompt" "configured"
        elif [ -n "$shown_default" ]; then
            printf '%s [%s]: ' "$prompt" "$shown_default"
        else
            printf '%s: ' "$prompt"
        fi
        IFS= read -r answer || answer=""
        if [ -z "$answer" ] && [ -n "$shown_default" ]; then
            answer="$shown_default"
        fi
        if [ -n "$answer" ] || [ "$required" -eq 0 ]; then
            env_set "$key" "$answer"
            break
        fi
        echo "  $key is required."
    done
}

if [ ! -f "$ENV_PATH" ]; then
    if [ ! -f "$ENV_TEMPLATE" ]; then
        echo "install_skills_conda: cannot create .env because .env-template is missing." >&2
        exit 1
    fi
    cp "$ENV_TEMPLATE" "$ENV_PATH"
    ENV_CREATED=1
    echo "[4/4] Created $ENV_PATH from .env-template"
else
    echo "[4/4] Updating $ENV_PATH"
fi

if [ "$INTERACTIVE" -eq 1 ]; then
    echo
    echo "Configure runtime environment variables."
    echo "Press Enter to keep the value shown in brackets. Secrets are preserved when already configured."
    echo

    ask_env "REPO_PATH" "Repository path" "$REPO_ROOT" 1 0
    ask_env "WORKSPACE_PATH" "Installed skills path" "$TARGET" 1 0
    if [ -z "$(env_get STORAGE_PROVIDER || true)" ]; then
        env_set "STORAGE_PROVIDER" "local"
    fi
    ask_env "LOCAL_STORAGE_PATH" "Local application storage path" "$REPO_ROOT/.storage" 1 0
    ask_env "CLOUD_PROVIDER" "Cloud provider (blank or google)" "google" 0 0
    cloud_provider=$(env_get CLOUD_PROVIDER || true)
    case "$(printf '%s' "$cloud_provider" | tr '[:upper:]' '[:lower:]')" in
        "") ;;
        google)
            ask_env "CLOUD_STORAGE_PATH" "Google Drive folder ID, root, or folder path/name" "" 1 0
            ;;
        *)
            echo "  CLOUD_PROVIDER must be blank or google." >&2
            exit 1
            ;;
    esac

    ask_env "QDRANT_HOST" "Qdrant host" "$(env_get QDRANT_HOST || true)" 1 0
    ask_env "OLLAMA_HOST" "Ollama host (fallback for local Ollama models)" "$(env_get OLLAMA_HOST || true)" 1 0
    ask_env "LLM_MODEL" "LLM model" "$(env_get LLM_MODEL || true)" 1 0
    ask_env "LLM_BASE_URL" "LLM base URL (blank for provider default)" "$(env_get LLM_BASE_URL || true)" 0 0
    ask_env "LLM_API_KEY" "LLM API key (blank if unused)" "$(env_get LLM_API_KEY || true)" 0 1
    ask_env "VLM_MODEL" "VLM model" "$(env_get VLM_MODEL || true)" 1 0
    vlm_base_default=$(env_get VLM_BASE_URL || true)
    if [ -z "$vlm_base_default" ]; then
        vlm_model_current=$(env_get VLM_MODEL || true)
        if [[ "$vlm_model_current" == ollama/* ]]; then
            vlm_base_default=$(env_get OLLAMA_HOST || true)
        else
            vlm_base_default=$(env_get LLM_BASE_URL || true)
        fi
    fi
    vlm_key_default=$(env_get VLM_API_KEY || true)
    if [ -z "$vlm_key_default" ]; then
        vlm_key_default=$(env_get LLM_API_KEY || true)
    fi
    ask_env "VLM_BASE_URL" "VLM base URL (local Ollama VLMs should use OLLAMA_HOST)" "$vlm_base_default" 0 0
    ask_env "VLM_API_KEY" "VLM API key (defaults to LLM_API_KEY)" "$vlm_key_default" 0 1
    ask_env "EMBEDDING_MODEL" "Embedding model" "$(env_get EMBEDDING_MODEL || true)" 1 0
    ask_env "EMBEDDING_BASE_URL" "Embedding base URL (blank for provider default)" "$(env_get EMBEDDING_BASE_URL || true)" 0 0
    ask_env "EMBEDDING_API_KEY" "Embedding API key (blank if unused)" "$(env_get EMBEDDING_API_KEY || true)" 0 1
    ask_env "GDRIVE_CREDENTIALS" "Google credentials path (blank to use default)" "$(env_get GDRIVE_CREDENTIALS || true)" 0 1
    ask_env "GDRIVE_TOKEN" "Google token path (blank to use default)" "$(env_get GDRIVE_TOKEN || true)" 0 1
    ask_env "GEMINI_API_KEY" "Gemini API key (blank if unused)" "$(env_get GEMINI_API_KEY || true)" 0 1
    ask_env "APIFY_KEY" "Apify API key (blank if unused)" "$(env_get APIFY_KEY || true)" 0 1
    ask_env "DEALUM_API_KEY" "Dealum API key (blank if unused)" "$(env_get DEALUM_API_KEY || true)" 0 1
    ask_env "DEALUM_DEALROOM_ID" "Dealum deal room ID (blank if unused)" "$(env_get DEALUM_DEALROOM_ID || true)" 0 1
    ask_env "DEALUM_SYNC_TTL_SECONDS" "Dealum sync TTL in seconds" "$(env_get DEALUM_SYNC_TTL_SECONDS || true)" 0 0
else
    echo "[4/4] .env prompts skipped (--non-interactive)."
    if [ -z "$(env_get REPO_PATH || true)" ]; then env_set "REPO_PATH" "$REPO_ROOT"; fi
    if [ -z "$(env_get WORKSPACE_PATH || true)" ]; then env_set "WORKSPACE_PATH" "$TARGET"; fi
    if [ -z "$(env_get STORAGE_PROVIDER || true)" ]; then env_set "STORAGE_PROVIDER" "local"; fi
fi

echo
echo "Done."
