#!/bin/sh
# install.sh - conda-based installer for SICTIC-AI.
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
#   2. Registers the installed workspace in the environment's site-packages using
#      a generated .pth file, without invoking project dependency resolution.
#   3. Copies every skill directory into <target>/<name>/ for skill discovery,
#      and also copies runnable packages/support files into <target>/.
#      Existing installed skill directories are preserved under
#      <target>/.skill-copy-backups/.
#
# Usage:
#   ./install.sh                                      # interactive install
#   ./install.sh --target /path/to/openclaw/skills    # optional target override
#   ./install.sh --rebuild-env                        # force a fresh conda env
#   ./install.sh --skip-env                           # skip steps 1+2
#   ./install.sh --non-interactive --target ...       # do not prompt for .env values

set -eu

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
TARGET=""
ENV_FILE="$REPO_ROOT/environment.yml"
REBUILD_ENV=0
SKIP_ENV=0
INTERACTIVE=1
SCRIPT_NAME=$(basename "$0")

usage() {
    sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
    case "$1" in
        --target) TARGET="$2"; shift 2 ;;
        --source) REPO_ROOT="$(cd "$2" && pwd)"; ENV_FILE="$REPO_ROOT/environment.yml"; shift 2 ;;
        --prune) shift ;; # Kept for backwards compatibility; install mode handles files.
        --rebuild-env) REBUILD_ENV=1; shift ;;
        --skip-env) SKIP_ENV=1; shift ;;
        --copy) shift ;; # Kept for backwards compatibility; copying is now the only mode.
        --non-interactive) INTERACTIVE=0; shift ;;
        --symlink) echo "install.sh: --symlink is no longer supported; copying skill files instead." >&2; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
    esac
done

env_file_get() {
    key="$1"
    path="$2"
    if [ ! -f "$path" ]; then
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
    ' "$path"
}

if [ -z "$TARGET" ]; then
    if [ "$INTERACTIVE" -eq 1 ]; then
        target_default=$(env_file_get WORKSPACE_PATH "$REPO_ROOT/.env" || true)
        while [ -z "$TARGET" ]; do
            if [ -n "$target_default" ]; then
                printf 'Installed skills path [%s]: ' "$target_default"
            else
                printf 'Installed skills path: '
            fi
            IFS= read -r target_answer || target_answer=""
            if [ -z "$target_answer" ]; then
                target_answer="$target_default"
            fi
            TARGET="$target_answer"
            if [ -z "$TARGET" ]; then
                echo "  WORKSPACE_PATH is required."
            fi
        done
    else
        echo "install.sh: --target is required with --non-interactive." >&2
        usage
        exit 2
    fi
fi

# Ensure TARGET resolves to an absolute path for user-facing metadata.
mkdir -p "$TARGET"
TARGET="$(cd "$TARGET" && pwd)"

if [ ! -d "$REPO_ROOT/skills" ]; then
    echo "install.sh: $REPO_ROOT/skills not found." >&2
    exit 1
fi
if [ ! -f "$ENV_FILE" ]; then
    echo "install.sh: $ENV_FILE not found." >&2
    exit 1
fi
if ! command -v conda >/dev/null 2>&1; then
    echo "install.sh: 'conda' not on PATH. Install Miniforge first:" >&2
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
    echo "install.sh: could not read 'name:' from $ENV_FILE." >&2
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
        echo "install.sh: cannot rebuild '$ENV_NAME' while it is the active conda environment." >&2
        echo >&2
        echo "Run this first:" >&2
        echo "    conda deactivate" >&2
        echo >&2
        echo "Then rerun the installer:" >&2
        echo "    ./$SCRIPT_NAME --target \"$TARGET\" --rebuild-env" >&2
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
            -o -type f -exec cp -p "{}" "$dst_dir/{}" \;
    )
}

copy_runtime_dir() {
    src_dir="$1"
    dst_dir="$2"

    [ -d "$src_dir" ] || return 0
    rm -rf "$dst_dir"
    mkdir -p "$dst_dir"
    (
        cd "$src_dir"
        find . \
            \( -name __pycache__ -o -name .DS_Store -o -name '*.pyc' \) -prune \
            -o -type d -exec mkdir -p "$dst_dir/{}" \; \
            -o -type f -exec cp -p "{}" "$dst_dir/{}" \;
    )
}

copy_support_file() {
    src_file="$1"
    dst_file="$2"

    [ -f "$src_file" ] || return 0
    cp -p "$src_file" "$dst_file"
}

BACKUP_ROOT=""

backup_existing_skill() {
    dst="$1"
    backup_name=$(basename "$dst")

    if [ -z "$BACKUP_ROOT" ]; then
        BACKUP_ROOT="$TARGET/.skill-copy-backups/$(date +%Y%m%d-%H%M%S)"
        mkdir -p "$BACKUP_ROOT"
    fi

    backup_path="$BACKUP_ROOT/$backup_name"
    counter=1
    while [ -e "$backup_path" ] || [ -L "$backup_path" ]; do
        backup_path="$BACKUP_ROOT/$backup_name-$counter"
        counter=$((counter + 1))
    done

    mv "$dst" "$backup_path"
    echo "       ~ preserved existing $backup_name at $backup_path"
}

echo "Installing SICTIC-AI (conda variant)"
echo "  source:   $REPO_ROOT"
echo "  target:   $TARGET"
echo "  env name: $ENV_NAME"
echo "  env file: $ENV_FILE"
echo "  skills:   copy"
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
                        echo "install.sh: rebuild required for the pinned Docling runtime. Re-run with --rebuild-env when ready." >&2
                        exit 1
                        ;;
                esac
            else
                echo "install.sh: rebuild required for Python $DESIRED_PYTHON. Re-run with --rebuild-env." >&2
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
        echo "install.sh: could not resolve python path in '$ENV_NAME'." >&2
        exit 1
    fi

else
    echo "[1+2/3] conda env: skipped (--skip-env)"
    ENV_PY=$(conda run -n "$ENV_NAME" --no-capture-output which python 2>/dev/null | tail -1 | tr -d '\r' || true)
    if [ -z "$ENV_PY" ] || [ ! -x "$ENV_PY" ]; then
        echo "install.sh: --skip-env requested but env '$ENV_NAME' has no usable python." >&2
        exit 1
    fi
fi

echo "[2/3] Registering installed workspace import path in $ENV_NAME..."
"$ENV_PY" -m pip uninstall --yes sictic-skills >/dev/null 2>&1 || true
SITE_PACKAGES=$("$ENV_PY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
if [ -z "$SITE_PACKAGES" ] || [ ! -d "$SITE_PACKAGES" ]; then
    echo "install.sh: could not resolve site-packages in '$ENV_NAME'." >&2
    exit 1
fi
printf '%s\n' "$TARGET" > "$SITE_PACKAGES/sictic-ai-repo.pth"

# ---------------------------------------------------------------------------
# Step 3: install skills
# ---------------------------------------------------------------------------
echo "[3/3] Copying skills into $TARGET ..."

INSTALLED_LIST=""
installed_count=0

for src in "$REPO_ROOT/skills"/*/; do
    src="${src%/}"
    name=$(basename "$src")
    [ -f "$src/SKILL.md" ] || continue

    dst="$TARGET/$name"

    if [ -e "$dst" ] || [ -L "$dst" ]; then
        backup_existing_skill "$dst"
    fi
    copy_skill_dir "$src" "$dst"

    INSTALLED_LIST="$INSTALLED_LIST $name "
    installed_count=$((installed_count + 1))
    echo "       + $name"
done

cat > "$TARGET/_SICTIC_AI.md" <<EOF
# SICTIC-AI skills

These skill directories are installed from \`$REPO_ROOT/skills/\` by:

    $REPO_ROOT/install.sh

The installer copies skill files into the workspace so skill discovery does not
depend on symlink support. Re-run the installer after changing \`SKILL.md\`
files or adding/removing skills.

The installer also copies runnable \`skills/\`, \`lib/\`, \`config/\`, and support
files into this workspace. It registers \`$TARGET\` in the \`$ENV_NAME\` conda
environment, so harness commands execute the installed copy rather than the
source repository. Runtime dependencies come only from \`environment.yml\`.

## Invocation

Each SKILL.md "Usage" section contains a harness slash command.
EOF

echo "       Installed $installed_count skill(s)."

echo "       Copying runtime packages and support files..."
copy_runtime_dir "$REPO_ROOT/skills" "$TARGET/skills"
copy_runtime_dir "$REPO_ROOT/lib" "$TARGET/lib"
copy_runtime_dir "$REPO_ROOT/config" "$TARGET/config"
copy_runtime_dir "$REPO_ROOT/scripts" "$TARGET/scripts"
copy_support_file "$REPO_ROOT/environment.yml" "$TARGET/environment.yml"
copy_support_file "$REPO_ROOT/launch.sh" "$TARGET/launch.sh"
copy_support_file "$REPO_ROOT/README.md" "$TARGET/README.md"
copy_support_file "$REPO_ROOT/.env-template" "$TARGET/.env-template"

# ---------------------------------------------------------------------------
# Step 4: interactive .env setup
# ---------------------------------------------------------------------------
SOURCE_ENV_PATH="$REPO_ROOT/.env"
ENV_PATH="$TARGET/.env"
ENV_TEMPLATE="$TARGET/.env-template"
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

source_env_get() {
    key="$1"
    env_file_get "$key" "$SOURCE_ENV_PATH"
}

env_default() {
    key="$1"
    fallback="$2"
    current=$(env_get "$key" || true)
    if [ -n "$current" ]; then
        printf '%s\n' "$current"
        return
    fi
    source_value=$(source_env_get "$key" || true)
    if [ -n "$source_value" ]; then
        printf '%s\n' "$source_value"
        return
    fi
    printf '%s\n' "$fallback"
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

env_has() {
    key="$1"
    if [ ! -f "$ENV_PATH" ]; then
        return 1
    fi
    grep -q "^[[:space:]]*$key[[:space:]]*=" "$ENV_PATH"
}

env_unset() {
    key="$1"
    if [ ! -f "$ENV_PATH" ]; then
        return
    fi
    tmp="$ENV_PATH.tmp.$$"
    awk -F= -v k="$key" '
        $0 ~ "^[[:space:]]*" k "[[:space:]]*=" { next }
        { print }
    ' "$ENV_PATH" > "$tmp"
    mv "$tmp" "$ENV_PATH"
}

prune_legacy_env_vars() {
    removed=""
    for key in \
        DEFAULT_LLM \
        DEFAULT_EMBEDDINGS \
        DEFAULT_VLM \
        MAX_CONCURRENT_DOCLING \
        MAX_CONCURRENT_EMBEDS \
        MAX_CONCURRENT_LLMS \
        OLLAMA_NUM_CTX \
        OLLAMA_NUM_CTX_MAX \
        REPO_DIR \
        WORKSPACE_DIR \
        STORAGE_MIRROR_DIR \
        STORAGE_MIRROR_PATH \
        STORAGE_PATH \
        STORAGE_PROVIDER \
        SICTIC_SYNC_DAEMON
    do
        if env_has "$key"; then
            env_unset "$key"
            removed="$removed $key"
        fi
    done
    if [ -n "$removed" ]; then
        echo "Removed legacy .env variables:$removed"
    fi
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
        echo "install.sh: cannot create .env because .env-template is missing." >&2
        exit 1
    fi
    cp "$ENV_TEMPLATE" "$ENV_PATH"
    ENV_CREATED=1
    echo "[4/4] Created $ENV_PATH from .env-template"
else
    echo "[4/4] Updating $ENV_PATH"
fi

prune_legacy_env_vars

if [ "$INTERACTIVE" -eq 1 ]; then
    echo
    echo "Configure runtime environment variables."
    echo "Press Enter to keep the value shown in brackets. Secrets are preserved when already configured."
    echo

    ask_env "REPO_PATH" "Repository path" "$TARGET" 1 0
    ask_env "WORKSPACE_PATH" "Installed skills path" "$TARGET" 1 0
    ask_env "LOCAL_STORAGE_PATH" "Local application storage path" "$(env_default LOCAL_STORAGE_PATH "$TARGET/.storage")" 1 0
    ask_env "LOCAL_DATA_PATH" "Local runtime cache path" "$(env_default LOCAL_DATA_PATH "$TARGET")" 1 0
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

    ask_env "QDRANT_HOST" "Qdrant host" "$(env_default QDRANT_HOST "")" 1 0
    ask_env "OLLAMA_HOST" "Ollama host (fallback for local Ollama models)" "$(env_default OLLAMA_HOST "")" 1 0
    ask_env "LLM_MODEL" "LLM model" "$(env_default LLM_MODEL "")" 1 0
    ask_env "LLM_BASE_URL" "LLM base URL (blank for provider default)" "$(env_default LLM_BASE_URL "")" 0 0
    ask_env "LLM_API_KEY" "LLM API key (blank if unused)" "" 0 1
    ask_env "RANKED_LLMS" "Reusable insight model ranking CSV" "$(env_default RANKED_LLMS "")" 1 0
    ask_env "VLM_MODEL" "VLM model" "$(env_default VLM_MODEL "")" 1 0
    vlm_base_default=$(env_default VLM_BASE_URL "")
    if [ -z "$vlm_base_default" ]; then
        vlm_model_current=$(env_default VLM_MODEL "")
        case "$vlm_model_current" in
            ollama/*) vlm_base_default=$(env_default OLLAMA_HOST "") ;;
            *) vlm_base_default=$(env_default LLM_BASE_URL "") ;;
        esac
    fi
    ask_env "VLM_BASE_URL" "VLM base URL (local Ollama VLMs should use OLLAMA_HOST)" "$vlm_base_default" 0 0
    ask_env "VLM_API_KEY" "VLM API key (defaults to LLM_API_KEY)" "" 0 1
    ask_env "EMBEDDING_MODEL" "Embedding model" "$(env_default EMBEDDING_MODEL "")" 1 0
    ask_env "EMBEDDING_BASE_URL" "Embedding base URL (blank for provider default)" "$(env_default EMBEDDING_BASE_URL "")" 0 0
    ask_env "EMBEDDING_API_KEY" "Embedding API key (blank if unused)" "" 0 1
    ask_env "OLLAMA_CONTEXT_LENGTH" "Ollama baseline context length" "$(env_default OLLAMA_CONTEXT_LENGTH "")" 1 0
    ask_env "OLLAMA_CONTEXT_LENGTH_MAX" "Ollama maximum context length" "$(env_default OLLAMA_CONTEXT_LENGTH_MAX "")" 1 0
    ask_env "OLLAMA_NUM_PARALLEL" "Ollama parallel request limit" "$(env_default OLLAMA_NUM_PARALLEL "")" 1 0
    ask_env "OLLAMA_MAX_LOADED_MODELS" "Ollama max loaded models" "$(env_default OLLAMA_MAX_LOADED_MODELS "")" 1 0
    ask_env "OLLAMA_KV_CACHE_TYPE" "Ollama KV cache type" "$(env_default OLLAMA_KV_CACHE_TYPE "")" 0 0
    ask_env "OLLAMA_FLASH_ATTENTION" "Ollama flash attention flag" "$(env_default OLLAMA_FLASH_ATTENTION "")" 0 0
    ask_env "GDRIVE_CREDENTIALS" "Google credentials path (blank to use default)" "" 0 1
    ask_env "GDRIVE_TOKEN" "Google token path (blank to use default)" "" 0 1
    ask_env "GEMINI_API_KEY" "Gemini API key (blank if unused)" "" 0 1
    ask_env "APIFY_KEY" "Apify API key (blank if unused)" "" 0 1
    ask_env "DEALUM_API_KEY" "Dealum API key (blank if unused)" "" 0 1
    ask_env "DEALUM_DEALROOM_ID" "Dealum deal room ID (blank if unused)" "" 0 1
    ask_env "DEALUM_SYNC_TTL_SECONDS" "Dealum sync TTL in seconds" "$(env_default DEALUM_SYNC_TTL_SECONDS "")" 0 0
else
    echo "[4/4] .env prompts skipped (--non-interactive)."
    if [ -z "$(env_get REPO_PATH || true)" ]; then env_set "REPO_PATH" "$TARGET"; fi
    if [ -z "$(env_get WORKSPACE_PATH || true)" ]; then env_set "WORKSPACE_PATH" "$TARGET"; fi
    if [ -z "$(env_get LOCAL_STORAGE_PATH || true)" ]; then env_set "LOCAL_STORAGE_PATH" "$(env_default LOCAL_STORAGE_PATH "$TARGET/.storage")"; fi
    if [ -z "$(env_get LOCAL_DATA_PATH || true)" ]; then env_set "LOCAL_DATA_PATH" "$(env_default LOCAL_DATA_PATH "$TARGET")"; fi
fi

echo
echo "Done."
