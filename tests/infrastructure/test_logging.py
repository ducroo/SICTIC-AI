import logging
import warnings

import pytest

import lib.infrastructure.logging as application_logging
from lib.infrastructure.errors import InfrastructureError


@pytest.fixture(autouse=True)
def reset_application_logging():
    root = logging.getLogger()
    original_level = root.level
    application_logging._reset_logging_for_tests()
    yield
    application_logging._reset_logging_for_tests()
    root.setLevel(original_level)
    logging.captureWarnings(False)


def _use_log_file(monkeypatch, tmp_path):
    log_file = tmp_path / "logs" / "sictic-ai.log"
    monkeypatch.delenv("SICTIC_TESTING", raising=False)
    monkeypatch.setattr(application_logging, "LOG_DIR", log_file.parent)
    monkeypatch.setattr(application_logging, "LOG_FILE", log_file)
    return log_file


def _flush_managed_handlers():
    for handler in application_logging._managed_handlers(
        logging.getLogger()
    ):
        handler.flush()


def test_testing_logger_does_not_install_file_handler(monkeypatch, tmp_path):
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("SICTIC_TESTING", "1")
    monkeypatch.setattr(application_logging, "LOG_DIR", log_dir)
    monkeypatch.setattr(
        application_logging,
        "LOG_FILE",
        log_dir / "sictic-ai.log",
    )

    application_logging.get_logger("tests.no-operational-file-log")

    assert application_logging._managed_handlers(logging.getLogger()) == []
    assert not log_dir.exists()


def test_debug_is_the_default_level(monkeypatch):
    monkeypatch.setenv("SICTIC_TESTING", "1")
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    logger = application_logging.get_logger("tests.default-level")

    assert logger.getEffectiveLevel() == logging.DEBUG


def test_log_level_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("SICTIC_TESTING", "1")
    monkeypatch.setenv("LOG_LEVEL", "warning")

    logger = application_logging.get_logger("tests.configured-level")

    assert logger.getEffectiveLevel() == logging.WARNING


def test_invalid_log_level_is_a_configuration_error(monkeypatch):
    monkeypatch.setenv("SICTIC_TESTING", "1")
    monkeypatch.setenv("LOG_LEVEL", "verbose")

    with pytest.raises(InfrastructureError, match="Invalid LOG_LEVEL"):
        application_logging.get_logger("tests.invalid-level")


def test_named_loggers_share_one_file_handler(monkeypatch, tmp_path):
    log_file = _use_log_file(monkeypatch, tmp_path)

    first = application_logging.get_logger("tests.first")
    second = application_logging.get_logger("tests.second")
    first.info("first message")
    second.warning("second message")
    _flush_managed_handlers()

    handlers = application_logging._managed_handlers(logging.getLogger())
    assert len(handlers) == 1
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert "| INFO     | tests.first | first message" in lines[0]
    assert "| WARNING  | tests.second | second message" in lines[1]


def test_third_party_python_logs_use_the_shared_file(monkeypatch, tmp_path):
    log_file = _use_log_file(monkeypatch, tmp_path)
    application_logging.get_logger("tests.application")

    logging.getLogger("third_party.client").warning("provider warning")
    _flush_managed_handlers()

    content = log_file.read_text(encoding="utf-8")
    assert "| WARNING  | third_party.client | provider warning" in content


def test_python_warnings_use_the_shared_file(monkeypatch, tmp_path):
    log_file = _use_log_file(monkeypatch, tmp_path)
    application_logging.get_logger("tests.application")

    warnings.warn("deprecated provider option", UserWarning)
    _flush_managed_handlers()

    content = log_file.read_text(encoding="utf-8")
    assert "py.warnings" in content
    assert "deprecated provider option" in content


def test_log_file_setup_failure_is_an_infrastructure_error(
    monkeypatch,
    tmp_path,
):
    invalid_directory = tmp_path / "not-a-directory"
    invalid_directory.write_text("occupied", encoding="utf-8")
    monkeypatch.delenv("SICTIC_TESTING", raising=False)
    monkeypatch.setattr(
        application_logging,
        "LOG_DIR",
        invalid_directory,
    )
    monkeypatch.setattr(
        application_logging,
        "LOG_FILE",
        invalid_directory / "sictic-ai.log",
    )

    with pytest.raises(InfrastructureError, match="Cannot open"):
        application_logging.get_logger("tests.file-error")
