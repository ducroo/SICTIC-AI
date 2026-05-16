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
#      rewriting `./run X` -> `<repo_abs>/run X` so the openclaw agent gets
#      unambiguous commands regardless of its CWD.
#   4. Removes any stale `env.vars.PYTHONPATH` from ~/.openclaw/openclaw.json
#      (the editable install makes it unnecessary, and a stale value actively
#      breaks skill imports).
#
# Usage:
#   ./install_skills.sh                       # default target, full bootstrap
#   ./install_skills.sh --target /custom/dir  # custom openclaw skill dir
#   ./install_skills.sh --symlink             # symlink mirrors instead of copy
#   ./install_skills.sh --prune               # remove target subdirs no longer in source
#   ./install_skills.sh --rebuild-venv        # force a fresh venv even if one exists
#   ./install_skills.sh --skip-venv           # skip steps 1+2 (skills + openclaw.json only)
#   ./install_skills.sh --skip-openclaw-json  # skip step 4

set -eu

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
TARGET="$HOME/.openclaw/skills/workspace-skills"
OPENCLAW_JSON="$HOME/.openclaw/openclaw.json"
MODE="copy"
PRUNE=0
REBUILD_VENV=0
SKIP_VENV=0
SKIP_OPENCLAW_JSON=0

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
        --skip-openclaw-json) SKIP_OPENCLAW_JSON=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
    esac
done

if [ ! -d "$REPO_ROOT/skills" ]; then
    echo "install_skills: $REPO_ROOT/skills not found." >&2
    exit 1
fi
if [ ! -x "$REPO_ROOT/run" ]; then
    echo "install_skills: $REPO_ROOT/run not found or not executable." >&2
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
        echo "[1/4] venv: not found — creating..."
        needs_rebuild=1
    elif [ "$REBUILD_VENV" -eq 1 ]; then
        echo "[1/4] venv: --rebuild-venv — recreating from scratch..."
        needs_rebuild=1
    else
        # The shebang line of venv/bin/pip points to the python that owns the
        # venv. If it doesn't include this repo's path, the venv was moved or
        # copied from elsewhere and is unsafe to reuse.
        shebang=$(head -1 "$venv_pip" 2>/dev/null || true)
        case "$shebang" in
            *"$VENV/"*)
                echo "[1/4] venv: present and anchored to this repo. Keeping it."
                ;;
            *)
                echo "[1/4] venv: shebang doesn't match repo path (was moved) — rebuilding..."
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

    echo "[2/4] pip install -e . (editable install + runtime deps from pyproject.toml)..."
    # --quiet keeps output tame; we still see errors.
    "$venv_pip" install --quiet -e "$REPO_ROOT"
else
    echo "[1+2/4] venv: skipped (--skip-venv)"
fi

# ---------------------------------------------------------------------------
# Step 3: mirror skills + rewrite ./run to absolute path
# ---------------------------------------------------------------------------
echo "[3/4] Mirroring skills into $TARGET ..."
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
            sed -i.bak "s|\\./run |$REPO_ROOT/run |g" "$dst/SKILL.md"
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

SKILL.md files in this directory reference \`$REPO_ROOT/run\` (absolute path).
The agent should always invoke a skill via:

    $REPO_ROOT/run <skill_name> [args...]

Override the Python interpreter with:

    export SICTIC_PYTHON=/path/to/python
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

# ---------------------------------------------------------------------------
# Step 4: remove stale PYTHONPATH from openclaw.json
# ---------------------------------------------------------------------------
if [ "$SKIP_OPENCLAW_JSON" -eq 0 ] && [ -f "$OPENCLAW_JSON" ]; then
    echo "[4/4] Checking $OPENCLAW_JSON for stale env.vars.PYTHONPATH ..."
    # Use the venv's python (we just ensured it works) to do a safe JSON edit.
    PY="$REPO_ROOT/venv/bin/python"
    if [ ! -x "$PY" ]; then
        PY="$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)"
    fi
    if [ -n "$PY" ] && [ -x "$PY" ]; then
        "$PY" - "$OPENCLAW_JSON" <<'PYEOF'
import json, shutil, sys
path = sys.argv[1]
with open(path) as f:
    cfg = json.load(f)
env_vars = cfg.get("env", {}).get("vars", {})
if "PYTHONPATH" in env_vars:
    shutil.copyfile(path, path + ".bak.install_skills")
    del env_vars["PYTHONPATH"]
    # If env.vars became empty, leave the dict in place (harmless).
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
    print(f"       Removed stale env.vars.PYTHONPATH (backup: {path}.bak.install_skills)")
else:
    print("       No PYTHONPATH set in openclaw.json. Nothing to do.")
PYEOF
    else
        echo "       (no Python available to safely edit JSON; skipping)" >&2
    fi
elif [ "$SKIP_OPENCLAW_JSON" -eq 0 ]; then
    echo "[4/4] openclaw.json not found at $OPENCLAW_JSON; skipping."
else
    echo "[4/4] openclaw.json: skipped (--skip-openclaw-json)"
fi

echo
echo "Done."
