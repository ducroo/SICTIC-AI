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
    level = logging.DEBUG if verbose else logging.INFO
    root.setLevel(level)
    target_dir = Path(log_dir).expanduser() if log_dir else default_log_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    file_handler = next(
        (
            handler
            for handler in root.handlers
            if isinstance(handler, RotatingFileHandler)
        ),
        None,
    )
    if file_handler is None:
        file_handler = RotatingFileHandler(
            target_dir / "gdrive-sync.log",
            maxBytes=5_000_000,
            backupCount=5,
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    file_handler.setLevel(level)

    console_handler = next(
        (
            handler
            for handler in root.handlers
            if getattr(handler, "_gdrive_sync_console", False)
        ),
        None,
    )
    if console_handler is None:
        console_handler = logging.StreamHandler()
        console_handler._gdrive_sync_console = True
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)
    console_handler.setLevel(level)
