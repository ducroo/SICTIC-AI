"""Atomic publication of prepared local directory snapshots."""

import os
import shutil
import uuid
from pathlib import Path


def replace_directory_snapshot(staging: Path, target: Path) -> None:
    """Publish a same-filesystem staging directory, rolling back a failed rename."""
    backup = target.with_name(f".{target.name}-backup-{uuid.uuid4().hex}")
    target_existed = target.exists()
    if target_existed:
        os.replace(target, backup)
    try:
        os.replace(staging, target)
    except Exception:
        if target_existed and backup.exists():
            os.replace(backup, target)
        raise
    if backup.exists():
        shutil.rmtree(backup)
