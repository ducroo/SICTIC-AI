"""Runtime noise controls for short-lived CLI commands.

The local stack pulls in large optional libraries. Some of them log directly to
stderr for optional providers or shutdown cleanup, even when the command
succeeds. Keep user-facing harness output focused on skill results while leaving
our own logs in logs/sictic-ai.log.
"""

import logging
import os


def configure_runtime_noise() -> None:
    os.environ.setdefault("GRPC_VERBOSITY", "ERROR")
    os.environ.setdefault("GRPC_TRACE", "")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    os.environ.setdefault("ABSL_LOGGING_MIN_LOG_LEVEL", "3")

    for logger_name in (
        "LiteLLM",
        "litellm",
        "RapidOCR",
        "pypdfium2",
        "pypdfium2.internal.bases",
    ):
        logging.getLogger(logger_name).setLevel(logging.ERROR)

    try:
        import pypdfium2_cfg

        pypdfium2_cfg.DEBUG_AUTOCLOSE.value = logging.CRITICAL + 1
    except Exception:
        pass
