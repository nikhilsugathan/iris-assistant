"""
IRIS Centralized Logger
=======================
Provides a configured logger that writes daily rotating log files to the
``logs/`` directory at the project root.  Import with::

    from core.logger import get_logger
    logger = get_logger("MyModule")
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

# Resolve the project root (parent of this file's directory)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOGS_DIR = os.path.join(_PROJECT_ROOT, "logs")

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _ensure_logs_dir() -> None:
    """Create the logs directory if it does not already exist."""
    os.makedirs(_LOGS_DIR, exist_ok=True)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger that writes to both the console and a size-rotating log file.

    The log file is placed in ``<project_root>/logs/iris.log`` and rotated
    when it reaches 5 MB, keeping up to 5 backup files.

    Args:
        name: A short identifier for the subsystem (e.g. ``"Diagnostics"``).

    Returns:
        A :class:`logging.Logger` instance configured for the IRIS project.
    """
    logger = logging.getLogger(f"iris.{name}")

    # Avoid adding duplicate handlers when the same logger is requested
    # multiple times in the same process.
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # ── File handler (size-based rotation) ────────────────────────────
    try:
        _ensure_logs_dir()
        log_path = os.path.join(_LOGS_DIR, "iris.log")
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as exc:  # pragma: no cover — only fails on bad permissions
        logging.getLogger().warning("Could not create log file handler: %s", exc)

    # ── Console handler ─────────────────────────────────────────────────
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Prevent messages from propagating to the root logger and being
    # printed twice.
    logger.propagate = False

    return logger
