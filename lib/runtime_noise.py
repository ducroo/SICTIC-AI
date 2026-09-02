"""Native runtime noise controls for short-lived CLI commands.

The local stack pulls in large optional libraries. Some of them log directly to
stderr for optional providers or shutdown cleanup, even when the command
succeeds. Python logs and warnings are handled by the infrastructure logger;
this module only controls messages that bypass Python logging.
"""

import logging
import os
from contextlib import contextmanager


def configure_runtime_noise() -> None:
    os.environ.setdefault("GRPC_VERBOSITY", "ERROR")
    os.environ.setdefault("GRPC_TRACE", "")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    os.environ.setdefault("ABSL_LOGGING_MIN_LOG_LEVEL", "3")

    try:
        import pypdfium2_cfg

        pypdfium2_cfg.DEBUG_AUTOCLOSE.value = logging.CRITICAL + 1
    except Exception:
        pass


@contextmanager
def suppress_native_stderr():
    """Temporarily silence native extension writes to file descriptor 2.

    Some dependencies emit C/C++ Abseil/gRPC diagnostics directly to stderr
    while importing, before Python logging can control them. Use this only
    around known-noisy imports; do not wrap runtime execution where real errors
    need to be visible.
    """
    if os.environ.get("SICTIC_SHOW_NATIVE_WARNINGS") == "1":
        yield
        return

    try:
        original_fd = os.dup(2)
        with open(os.devnull, "w") as devnull:
            os.dup2(devnull.fileno(), 2)
            try:
                yield
            finally:
                os.dup2(original_fd, 2)
                os.close(original_fd)
    except Exception:
        yield
