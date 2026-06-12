from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


def default_log_dir() -> Path:
    repo_root = os.environ.get("REPO_PATH")
    if repo_root:
        return Path(repo_root).expanduser() / "logs"
    return Path(__file__).resolve().parents[2] / "logs"


def configure_logging(log_dir: str | None = None, *, verbose: bool = False) -> None:
    root = logging.getLogger("skills.gdrive_sync")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    if any(isinstance(handler, RotatingFileHandler) for handler in root.handlers):
        return
    target_dir = Path(log_dir).expanduser() if log_dir else default_log_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    file_handler = RotatingFileHandler(target_dir / "gdrive-sync.log", maxBytes=5_000_000, backupCount=5)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(file_handler)
