#!/bin/sh
# install_skills.sh — one-shot bootstrap for SICTIC-AI under openclaw.
#
# Run once after `git clone`, after moving the repo, or after editing SKILL.md.
# Idempotent: safe to re-run any time.
#
# What it does:
#   1. Ensures ./venv exists and is anchored to this repo's current location.
#      Rebuilds the venv if it was moved/copied from elsewhere.
#   2. Runs `pip install -e .` so the editable install (and all runtime deps
#      declared in pyproject.toml) reflects the current location.
#   3. Mirrors every skills/<name>/ that has a SKILL.md into <target>/<name>/,
#      substituting `{{REPO_ROOT}}` -> `<repo_abs>` in the mirrored SKILL.md so
#      every command becomes an absolute, copy-pastable invocation.
#
# This script never touches ~/.openclaw/openclaw.json or any other openclaw
# config — only the venv, the mirror target, and (transitively) pyproject.toml.
#
# Usage:
#   ./install_skills.sh --target /path/to/openclaw/skill/dir   # required
#   ./install_skills.sh --target ... --symlink                 # symlink mirrors instead of copy
#   ./install_skills.sh --target ... --prune                   # remove target subdirs no longer in source
#   ./install_skills.sh --target ... --rebuild-venv            # force a fresh venv even if one exists
#   ./install_skills.sh --target ... --skip-venv               # skip steps 1+2 (mirror only)

set -eu

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
TARGET=""
MODE="copy"
PRUNE=0
REBUILD_VENV=0
SKIP_VENV=0

usage() {
    sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
    case "$1" in
        --target) TARGET="$2"; shift 2 ;;
        --source) REPO_ROOT="$(cd "$2" && pwd)"; shift 2 ;;
        --symlink) MODE="symlink"; shift ;;
        --prune) PRUNE=1; shift ;;
        --rebuild-venv) REBUILD_VENV=1; shift ;;
        --skip-venv) SKIP_VENV=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
    esac
done

if [ -z "$TARGET" ]; then
    echo "install_skills: --target is required." >&2
    usage
    exit 2
fi
if [ ! -d "$REPO_ROOT/skills" ]; then
    echo "install_skills: $REPO_ROOT/skills not found." >&2
    exit 1
fi
if [ ! -f "$REPO_ROOT/pyproject.toml" ]; then
    echo "install_skills: $REPO_ROOT/pyproject.toml not found." >&2
    exit 1
fi

echo "Installing SICTIC-AI"
echo "  source: $REPO_ROOT"
echo "  target: $TARGET"
echo "  mode:   $MODE"
echo

# ---------------------------------------------------------------------------
# Step 1+2: venv bootstrap + editable install
# ---------------------------------------------------------------------------
if [ "$SKIP_VENV" -eq 0 ]; then
    VENV="$REPO_ROOT/venv"
    venv_pip="$VENV/bin/pip"

    needs_rebuild=0
    if [ ! -x "$venv_pip" ]; then
        echo "[1/3] venv: not found — creating..."
        needs_rebuild=1
    elif [ "$REBUILD_VENV" -eq 1 ]; then
        echo "[1/3] venv: --rebuild-venv — recreating from scratch..."
        needs_rebuild=1
    else
        # The shebang line of venv/bin/pip points to the python that owns the
        # venv. If it doesn't include this repo's path, the venv was moved or
        # copied from elsewhere and is unsafe to reuse.
        shebang=$(head -1 "$venv_pip" 2>/dev/null || true)
        case "$shebang" in
            *"$VENV/"*)
                echo "[1/3] venv: present and anchored to this repo. Keeping it."
                ;;
            *)
                echo "[1/3] venv: shebang doesn't match repo path (was moved) — rebuilding..."
                needs_rebuild=1
                ;;
        esac
    fi

    if [ "$needs_rebuild" -eq 1 ]; then
        rm -rf "$VENV"
        # Prefer python3.13 (current docling target), fall back to python3.
        if command -v python3.13 >/dev/null 2>&1; then
            python3.13 -m venv "$VENV"
        elif command -v python3 >/dev/null 2>&1; then
            python3 -m venv "$VENV"
        else
            echo "install_skills: no python3 found on PATH." >&2
            exit 1
        fi
        "$venv_pip" install --quiet --upgrade pip
    fi

    echo "[2/3] pip install -e . (editable install + runtime deps from pyproject.toml)..."
    # --quiet keeps output tame; we still see errors.
    "$venv_pip" install --quiet -e "$REPO_ROOT"
else
    echo "[1+2/3] venv: skipped (--skip-venv)"
fi

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
            # Substitute {{REPO_ROOT}} placeholder with the absolute repo path.
            # Source SKILL.md files mark every substitution point explicitly;
            # nothing here pattern-matches. Idempotent.
            sed -i.bak "s|{{REPO_ROOT}}|$REPO_ROOT|g" "$dst/SKILL.md"
            rm -f "$dst/SKILL.md.bak"
        fi
    fi

    INSTALLED_LIST="$INSTALLED_LIST $name"
    installed_count=$((installed_count + 1))
    echo "       + $name"
done

cat > "$TARGET/_SICTIC_AI.md" <<EOF
# SICTIC-AI skills (installed from $REPO_ROOT)

These skill directories were mirrored from \`$REPO_ROOT/skills/\` by:

    $REPO_ROOT/install_skills.sh

Re-run that command after editing SKILL.md or moving the repo.

## Invocation

Each SKILL.md "Usage" section contains absolute, copy-pastable commands of the form:

    $REPO_ROOT/venv/bin/python -m skills.<skill_name> [args...]

Run them exactly as written. The \`{{REPO_ROOT}}\` placeholder in the source
SKILL.md files has already been substituted to \`$REPO_ROOT\` in this mirror.
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
