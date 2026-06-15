import logging
from logging.handlers import RotatingFileHandler

from skills.gdrive_sync.logging_config import configure_logging


def test_configure_logging_adds_file_and_console_handlers(tmp_path):
    logger = logging.getLogger("skills.gdrive_sync")
    previous_handlers = list(logger.handlers)
    previous_propagate = logger.propagate
    try:
        logger.handlers.clear()

        configure_logging(str(tmp_path))
        configure_logging(str(tmp_path))

        file_handlers = [
            handler
            for handler in logger.handlers
            if isinstance(handler, RotatingFileHandler)
        ]
        console_handlers = [
            handler
            for handler in logger.handlers
            if getattr(handler, "_gdrive_sync_console", False)
        ]
        assert len(file_handlers) == 1
        assert len(console_handlers) == 1
    finally:
        for handler in logger.handlers:
            if handler not in previous_handlers:
                handler.close()
        logger.handlers[:] = previous_handlers
        logger.propagate = previous_propagate
