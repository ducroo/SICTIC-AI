"""Process-wide application logging configuration.

Every process appends to ``logs/sictic-ai.log`` through one rotating file
handler. The file is renamed to ``sictic-ai.log.1`` once it reaches
``LOG_MAX_BYTES`` and ``LOG_BACKUP_COUNT`` backups are kept, so the log
directory stays bounded whatever level is configured. Several long-running
processes (MCP servers, CLI runs) share the file and each rotates on its
own; the standard handler tolerates that, but a process may keep writing
into an already rotated, or already deleted, backup until its own next
rollover, so up to one file of that process's lines can be misplaced or
lost.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock
from typing import Final

from lib.infrastructure.configuration import get_env_var
from lib.infrastructure.errors import (
    InfrastructureError,
    InfrastructureErrorKind,
)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
LOG_DIR = _REPO_ROOT / "logs"
LOG_FILE = LOG_DIR / "sictic-ai.log"
LOG_MAX_BYTES = 10_000_000
LOG_BACKUP_COUNT = 5

_FORMAT: Final[str] = (
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
_DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"
_HANDLER_MARKER: Final[str] = "_sictic_ai_file_handler"
_CONFIGURATION_LOCK: Final[Lock] = Lock()


def _configured_level() -> int:
    configured = get_env_var("LOG_LEVEL", required=False) or "INFO"
    level = logging.getLevelNamesMapping().get(configured.upper())
    if not isinstance(level, int):
        supported = "DEBUG, INFO, WARNING, ERROR or CRITICAL"
        raise InfrastructureError(
            f"Invalid LOG_LEVEL {configured!r}; expected {supported}",
            kind=InfrastructureErrorKind.CONFIGURATION,
            provider="environment",
            operation="configure_logging",
        )
    return level


def _managed_handlers(root: logging.Logger) -> list[logging.Handler]:
    return [
        handler
        for handler in root.handlers
        if getattr(handler, _HANDLER_MARKER, False)
    ]


def _remove_managed_handlers(root: logging.Logger) -> None:
    for handler in _managed_handlers(root):
        root.removeHandler(handler)
        handler.close()


def _configure_logging() -> None:
    level = _configured_level()
    root = logging.getLogger()

    with _CONFIGURATION_LOCK:
        root.setLevel(level)
        logging.captureWarnings(True)

        if os.environ.get("SICTIC_TESTING") == "1":
            _remove_managed_handlers(root)
            return

        handlers = _managed_handlers(root)
        if handlers:
            for handler in handlers:
                handler.setLevel(level)
            return

        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(
                LOG_FILE,
                maxBytes=LOG_MAX_BYTES,
                backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
        except OSError as error:
            raise InfrastructureError(
                f"Cannot open application log file {LOG_FILE}: {error}",
                kind=InfrastructureErrorKind.CONFIGURATION,
                provider="filesystem",
                operation="configure_logging",
            ) from error

        setattr(handler, _HANDLER_MARKER, True)
        handler.setLevel(level)
        handler.setFormatter(
            logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)
        )
        root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger using the shared application configuration."""
    _configure_logging()
    logger = logging.getLogger(name)
    logger.setLevel(logging.NOTSET)
    return logger


def _reset_logging_for_tests() -> None:
    """Remove only the handler owned by this module."""
    with _CONFIGURATION_LOCK:
        _remove_managed_handlers(logging.getLogger())
