"""
logger.py — Centralized Logging Setup
======================================
Import get_logger() in any module to get a named logger that writes to both
the console and a rotating file. All loggers share the same handlers so there
is no duplicate output.

Usage:
    from logger import get_logger
    logger = get_logger(__name__)
    logger.info("Message")
    logger.error("Something went wrong", exc_info=True)
"""

import logging
import logging.handlers
from pathlib import Path

# pyrefly: ignore [missing-import]
import config 


def get_logger(name: str) -> logging.Logger:
    """
    Returns a named logger with console + rotating file handlers attached.
    Safe to call multiple times — handlers are only added once per logger name.
    """
    logger = logging.getLogger(name)

    # Guard: don't add duplicate handlers if already configured
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, config.LOG_LEVEL.upper(), logging.INFO))

    # Shared formatter: [2026-05-25 14:30:00] [INFO] [api] Message here
    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)-8s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── Console Handler ─────────────────────────────────────────────────────────
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # ── Rotating File Handler ───────────────────────────────────────────────────
    if config.LOG_FILE is not None:
        log_path: Path = config.LOG_FILE
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.handlers.RotatingFileHandler(
            filename=log_path,
            maxBytes=config.LOG_MAX_BYTES,
            backupCount=config.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # Prevent log records from bubbling up to the root logger (avoids duplicate output)
    logger.propagate = False

    return logger
