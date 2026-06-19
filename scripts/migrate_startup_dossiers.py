"""Compatibility launcher for dataset_maintenance startup dossier migration."""

import sys

from skills.dataset_maintenance.__main__ import app
from skills.dataset_maintenance.startup_dossiers import apply_plan, build_plan


if __name__ == "__main__":
    app(
        prog_name="migrate_startup_dossiers.py",
        args=["migrate-startup-dossiers", *sys.argv[1:]],
    )
