import logging
import os
from pathlib import Path

# Define the log directory and file
LOG_DIR = Path.home() / ".openclaw" / "workspace-sictic-ai" / "log"
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
