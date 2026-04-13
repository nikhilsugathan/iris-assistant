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
import threading
from logging.handlers import RotatingFileHandler

# Resolve the project root (parent of this file's directory)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOGS_DIR = os.path.join(_PROJECT_ROOT, "logs")

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


# ── Windows-safe rotation ────────────────────────────────────────────────────
# On Windows, RotatingFileHandler.doRollover() calls os.rename() which raises
# PermissionError (WinError 32) when any other handle has the log file open.
# We monkey-patch the method at import time so ALL RotatingFileHandler
# instances are protected — even if Python loads a cached .pyc that predates
# this module's last edit.

def _safe_rotating_doRollover(self) -> None:  # type: ignore[override]
    """doRollover that survives Windows file-lock errors (WinError 32).

    When os.rename() is blocked by another process holding an open handle,
    we fall back to truncating the current log file in place so IRIS can
    keep logging without flooding the console with tracebacks.
    """
    try:
        _original_rotating_doRollover(self)
    except PermissionError:
        # Rename blocked — truncate in place rather than crash.
        try:
            if self.stream:
                self.stream.close()
                self.stream = None
            with open(self.baseFilename, "w", encoding=self.encoding or "utf-8"):
                pass  # truncate
            if not self.delay:
                self.stream = self._open()
        except Exception:
            pass  # give up silently; next emit will reopen the stream


_original_rotating_doRollover = RotatingFileHandler.doRollover
RotatingFileHandler.doRollover = _safe_rotating_doRollover  # type: ignore[method-assign]


def _ensure_logs_dir() -> None:
    """Create the logs directory if it does not already exist."""
    os.makedirs(_LOGS_DIR, exist_ok=True)


# ── Shared trace handler (single instance for ALL iris.trace.* loggers) ──────
# Multiple RotatingFileHandler instances pointing at the same file is the
# root cause of WinError 32: handler A closes+renames iris_trace.log while
# handler B still has it open.  The fix: one parent logger ("iris.trace")
# holds the ONLY file handler; all child loggers propagate to it.

_trace_parent_lock = threading.Lock()
_trace_parent_ready = False


def _ensure_trace_parent() -> None:
    """Idempotently attach a single RotatingFileHandler to ``iris.trace``."""
    global _trace_parent_ready
    if _trace_parent_ready:
        return
    with _trace_parent_lock:
        if _trace_parent_ready:
            return
        parent = logging.getLogger("iris.trace")
        if not parent.handlers:
            parent.setLevel(logging.DEBUG)
            parent.propagate = False
            try:
                _ensure_logs_dir()
                log_path = os.path.join(_LOGS_DIR, "iris_trace.log")
                fh = RotatingFileHandler(
                    log_path,
                    maxBytes=5 * 1024 * 1024,
                    backupCount=3,
                    encoding="utf-8",
                )
                fh.setLevel(logging.INFO)
                fh.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
                parent.addHandler(fh)
            except Exception as exc:
                logging.getLogger().warning(
                    "Could not create trace log handler: %s", exc
                )
        _trace_parent_ready = True


def _configure_logger(
    *,
    full_name: str,
    filename: str,
    file_level: int,
    console_level: int | None,
) -> logging.Logger:
    logger = logging.getLogger(full_name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    try:
        _ensure_logs_dir()
        log_path = os.path.join(_LOGS_DIR, filename)
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=7,
            encoding="utf-8",
        )
        file_handler.setLevel(file_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as exc:  # pragma: no cover — only fails on bad permissions
        logging.getLogger().warning("Could not create log file handler: %s", exc)

    if console_level is not None:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(console_level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    logger.propagate = False
    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a named logger that writes to both the console and a daily log file.

    The log file is placed in ``<project_root>/logs/iris.log`` and rotated
    once per day, keeping up to 7 days of history.

    Args:
        name: A short identifier for the subsystem (e.g. ``"Diagnostics"``).

    Returns:
        A :class:`logging.Logger` instance configured for the IRIS project.
    """
    return _configure_logger(
        full_name=f"iris.{name}",
        filename="iris.log",
        file_level=logging.DEBUG,
        console_level=logging.WARNING,
    )


def get_trace_logger(name: str, filename: str = "iris_trace.log") -> logging.Logger:
    """Return a logger dedicated to always-on runtime tracing.

    All trace loggers share a SINGLE file handler on the ``iris.trace`` parent
    logger so only one RotatingFileHandler ever touches ``iris_trace.log``.
    This eliminates WinError 32 (file-lock conflicts during rotation) that
    occurred when ``iris.trace.Voice`` and ``iris.trace.Runtime`` each had
    their own handler pointing at the same file.

    Child loggers emit no console output and propagate silently to the parent.
    """
    _ensure_trace_parent()
    child = logging.getLogger(f"iris.trace.{name}")
    # Child must have NO direct handlers — only propagate to iris.trace.
    # Clear any stale handlers that may exist from a previous code version.
    if child.handlers:
        child.handlers.clear()
    child.setLevel(logging.DEBUG)
    child.propagate = True  # writes go to iris.trace → its single file handler
    return child
