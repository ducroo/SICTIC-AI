# SICTIC-AI skills

These skills run from the installed SICTIC-AI repository in the `sictic-env`
conda environment. Repository and storage locations vary by machine; do not
hardcode user-specific absolute paths in skill instructions.

## Storage

Use `LOCAL_STORAGE_PATH` as the storage root for synchronized application data.

Startup datasets live under:

    $LOCAL_STORAGE_PATH/storage/startups/<startup>/datasets/

Dealum imports write to:

    $LOCAL_STORAGE_PATH/storage/startups/<startup>/datasets/dealum/

To list local startup dataset folders:

    ls "$LOCAL_STORAGE_PATH/storage/startups"

## Invocation

Each SKILL.md "Usage" section contains commands of the form:

    python -m skills.<skill_name> [args...]

Run them inside `sictic-env`, or use `conda run -n sictic-env` when launching
from a plain shell.
