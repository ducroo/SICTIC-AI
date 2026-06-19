import logging

from lib.logger import get_logger


def test_testing_logger_does_not_install_file_handler(monkeypatch):
    monkeypatch.setenv("SICTIC_TESTING", "1")
    logger = logging.getLogger("tests.no-operational-file-log")
    logger.handlers.clear()

    configured = get_logger(logger.name)

    assert any(isinstance(handler, logging.NullHandler) for handler in configured.handlers)
    assert not any(isinstance(handler, logging.FileHandler) for handler in configured.handlers)
