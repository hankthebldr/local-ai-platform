#!/usr/bin/env python3
"""
Logging Configuration — Structured logging to console and file
"""

import os
import sys
import logging
import logging.handlers
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_DIR = os.getenv("LOG_DIR", "./data/logs")


def setup_logging(name: str = "local-ai") -> logging.Logger:
    """
    Configure structured logging with both console and rotating file output.

    Returns a logger instance ready to use.
    """
    logger = logging.getLogger(name)

    # Avoid duplicate handlers on reload
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    # ── Format ─────────────────────────────────────────────────────────
    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── Console handler ────────────────────────────────────────────────
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    console.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    logger.addHandler(console)

    # ── File handler (rotating, 10MB, keep 5) ──────────────────────────
    log_path = Path(LOG_DIR)
    log_path.mkdir(parents=True, exist_ok=True)
    log_file = log_path / "api.log"

    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)  # File gets everything
    logger.addHandler(file_handler)

    # Don't propagate to root logger
    logger.propagate = False

    return logger


# Module-level logger for import convenience
logger = setup_logging()
