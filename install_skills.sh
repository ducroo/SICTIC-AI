#!/bin/sh
# install_skills.sh — mirror SICTIC-AI skills into openclaw's skill directory.
#
# For each subdirectory of <source>/skills/ that contains a SKILL.md, install
# it into <target>/<name>/ so openclaw's agent can discover the skill. The
# SKILL.md examples that reference ./run are rewritten to use this repo's
# absolute path, so the agent gets unambiguous commands regardless of its CWD.
#
# All actual Python code stays in this repo. Re-run after editing SKILL.md
# or adding skills.
#
# Usage:
#   ./install_skills.sh                        # default target (see below)
#   ./install_skills.sh --target /custom/dir   # custom target
#   ./install_skills.sh --symlink              # symlink instead of copy
#   ./install_skills.sh --prune                # remove target subdirs no longer in source

set -eu

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
TARGET="$HOME/.openclaw/skills/workspace-skills"
MODE="copy"
PRUNE=0

usage() {
    sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
    case "$1" in
        --target) TARGET="$2"; shift 2 ;;
        --source) REPO_ROOT="$(cd "$2" && pwd)"; shift 2 ;;
        --symlink) MODE="symlink"; shift ;;
        --prune) PRUNE=1; shift ;;
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

echo "Installing SICTIC-AI skills"
echo "  source: $REPO_ROOT"
echo "  target: $TARGET"
echo "  mode:   $MODE"
echo

mkdir -p "$TARGET"

# Track which skill names we've installed this run, for optional --prune.
INSTALLED_LIST=""
installed_count=0

for src in "$REPO_ROOT/skills"/*/; do
    # The glob leaves a trailing slash; strip it for cp/ln correctness.
    src="${src%/}"
    name=$(basename "$src")

    # Only directories with a SKILL.md are user-facing skills.
    if [ ! -f "$src/SKILL.md" ]; then
        continue
    fi

    dst="$TARGET/$name"
    rm -rf "$dst"

    if [ "$MODE" = "symlink" ]; then
        ln -s "$src" "$dst"
    else
        cp -R "$src" "$dst"
        # Drop bytecode cache; not useful in the target.
        find "$dst" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
        # Rewrite `./run X` -> `<REPO_ROOT>/run X` so the agent has an
        # unambiguous absolute command regardless of its CWD.
        if [ -f "$dst/SKILL.md" ]; then
            sed -i.bak "s|\\./run |$REPO_ROOT/run |g" "$dst/SKILL.md"
            rm -f "$dst/SKILL.md.bak"
        fi
    fi

    INSTALLED_LIST="$INSTALLED_LIST $name"
    installed_count=$((installed_count + 1))
    echo "  + $name"
done

# Drop a marker file at the target root so future-you knows where these came from.
cat > "$TARGET/_SICTIC_AI.md" <<EOF
# SICTIC-AI skills (installed from $REPO_ROOT)

These skill directories were mirrored from \`$REPO_ROOT/skills/\` by:

    $REPO_ROOT/install_skills.sh

Re-run that command after editing SKILL.md or adding/renaming skills.

## Invocation

The SKILL.md files in this directory reference \`$REPO_ROOT/run\` (absolute path).
The agent should always invoke a skill via:

    $REPO_ROOT/run <skill_name> [args...]

Override the Python interpreter with:

    export SICTIC_PYTHON=/path/to/python
EOF

# Optional cleanup: remove target subdirs that aren't in source anymore.
if [ "$PRUNE" -eq 1 ]; then
    echo
    echo "Pruning target subdirs not present in source..."
    for d in "$TARGET"/*/; do
        [ -d "$d" ] || continue
        name=$(basename "$d")
        case " $INSTALLED_LIST " in
            *" $name "*) ;;  # keep
            *) echo "  - $name"; rm -rf "$d" ;;
        esac
    done
fi

echo
echo "Done. Installed $installed_count skill(s) into $TARGET"
