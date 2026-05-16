import logging
from pathlib import Path

# Logs land in the repo's logs/ directory (gitignored). Resolved from this file's
# location so it works regardless of CWD or which Python invokes the skill.
_REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = _REPO_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "sictic-ai.log"

def get_logger(name: str) -> logging.Logger:
    """
    Creates and returns a configured logger that writes to the central sictic-ai.log file.
    All errors, warnings, and info logs go to this unified file for easy chronological tracking.
    """
    logger = logging.getLogger(name)
    
    # Only configure if it doesn't already have handlers to avoid duplicate logs
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)  # Capture everything at the logger level

        # Create a file handler for all logs
        file_handler = logging.FileHandler(LOG_FILE)
        file_handler.setLevel(logging.DEBUG)

        # Define a standard format including the log level
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        
        logger.addHandler(file_handler)

    return logger
