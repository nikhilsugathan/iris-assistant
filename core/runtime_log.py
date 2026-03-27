"""
IRIS Runtime Log
================
Thin wrapper around core.logger for structured runtime event logging.
Satisfies the import in core/profile.py: `from core.runtime_log import log_runtime`
"""

from __future__ import annotations

from core.logger import get_logger

_logger = get_logger("RuntimeLog")


def log_runtime(event: str, *, level: str = "INFO", **kwargs) -> None:
    msg = event if not kwargs else f"{event} | {', '.join(f'{k}={v}' for k, v in kwargs.items())}"
    getattr(_logger, level.lower(), _logger.info)(msg)
